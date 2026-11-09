"""One-date Yahoo -> Supabase demo; Python 3.11+, standard library only."""
import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

SOURCE = 'yahoo_finance'
NY = ZoneInfo('America/New_York')


def now():
    return datetime.now(timezone.utc).isoformat()


def request_json(url, *, method='GET', headers=None, data=None):
    body = None if data is None else json.dumps(data, allow_nan=False).encode()
    req = Request(url, data=body, method=method, headers={
        'User-Agent': 'python-pricing-poc/1.0',
        'Content-Type': 'application/json', **(headers or {})})
    try:
        with urlopen(req, timeout=30) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except HTTPError as exc:
        # Do not dump request headers, credentials, or provider response bodies.
        raise RuntimeError(f'{urlsplit(url).hostname}: HTTP {exc.code}') from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f'{urlsplit(url).hostname}: network failure ({type(exc).__name__})') from None


def fetch_yahoo(symbol, target):
    # Padding accommodates exchange-local dates on either side of UTC.
    start = datetime.combine(target - timedelta(days=1), time(), timezone.utc)
    end = datetime.combine(target + timedelta(days=2), time(), timezone.utc)
    query = urlencode({'period1': int(start.timestamp()), 'period2': int(end.timestamp()),
                       'interval': '1d', 'events': 'history', 'includeAdjustedClose': 'true'})
    return request_json(f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe="")}?{query}')


def parse_yahoo(payload, symbol, target, run_id):
    chart = payload['chart']
    if chart.get('error'):
        raise ValueError(f'{symbol}: Yahoo reported an error')
    results = chart.get('result')
    if not results:
        raise ValueError(f'{symbol}: missing Yahoo result')
    result = results[0]
    meta = result['meta']
    if meta.get('symbol', '').upper() != symbol:
        raise ValueError(f'{symbol}: provider returned a different symbol')
    tz = ZoneInfo(meta['exchangeTimezoneName'])
    stamps = result.get('timestamp') or []
    indices = [i for i, stamp in enumerate(stamps)
               if datetime.fromtimestamp(stamp, tz).date() == target]
    if not indices:
        return None
    if len(indices) != 1:
        raise ValueError(f'{symbol}: expected exactly one daily bar')
    index = indices[0]
    quotes = result['indicators']['quote'][0]
    values = {}
    for field in ('open', 'high', 'low', 'close'):
        value = quotes[field][index]
        if value is None or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{symbol}: invalid {field}')
        values[field] = value
    if values['low'] > min(values['open'], values['close']) or values['high'] < max(values['open'], values['close']):
        raise ValueError(f'{symbol}: inconsistent OHLC')
    adjusted = result['indicators'].get('adjclose')
    adjusted_close = adjusted[0]['adjclose'][index] if adjusted else None
    if adjusted_close is not None and (not math.isfinite(adjusted_close) or adjusted_close <= 0):
        raise ValueError(f'{symbol}: invalid adjusted close')
    volume = quotes.get('volume', [None] * len(stamps))[index]
    if volume is not None and (not isinstance(volume, int) or volume < 0):
        raise ValueError(f'{symbol}: invalid volume')
    currency = meta.get('currency')
    if not currency:
        raise ValueError(f'{symbol}: missing quote currency')
    observed = now()
    security = {'yahoo_symbol': symbol, 'display_name': meta.get('longName') or meta.get('shortName'),
                'exchange': meta.get('exchangeName'), 'instrument_type': meta.get('instrumentType'),
                'updated_at': observed}
    price = {'yahoo_symbol': symbol, 'price_date': target.isoformat(), 'source': SOURCE,
             'currency': currency, **values, 'adjusted_close': adjusted_close,
             'volume': volume, 'fetched_at': observed, 'run_id': run_id}
    return security, price


class Supabase:
    def __init__(self):
        self.url = (os.environ.get('SUPABASE_URL') or os.environ.get('supabase_url', '')).rstrip('/')
        self.key = os.environ.get('SUPABASE_SECRET_KEY') or os.environ.get('supabase_secret_key', '')
        parsed = urlsplit(self.url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Set SUPABASE_URL to the project HTTPS origin')
        if not self.key:
            raise ValueError('Set SUPABASE_SECRET_KEY in your runner secret settings')

    def call(self, table, *, method='GET', data=None, query=None, upsert=False):
        headers = {'apikey': self.key, 'Prefer': 'return=representation'}
        # New sb_secret keys go only in apikey; legacy service_role JWTs also need Bearer.
        if not self.key.startswith('sb_secret_'):
            headers['Authorization'] = f'Bearer {self.key}'
        if upsert:
            headers['Prefer'] += ',resolution=merge-duplicates'
        url = f'{self.url}/rest/v1/{table}'
        if query:
            url += '?' + urlencode(query)
        return request_json(url, method=method, headers=headers, data=data)


def run(target, symbols, *, dry_run=False, output=None):
    run_id = str(uuid4())
    db = None if dry_run else Supabase()
    if db:
        db.call('poc_price_runs', method='POST', data={
            'id': run_id, 'price_date': target.isoformat(), 'requested_symbols': symbols,
            'source': SOURCE, 'status': 'running'})
    written = 0
    try:
        securities, prices, missing = [], [], []
        for symbol in symbols:
            parsed = parse_yahoo(fetch_yahoo(symbol, target), symbol, target, run_id)
            if parsed is None:
                missing.append(symbol)
            else:
                security, price = parsed
                securities.append(security)
                prices.append(price)
        # No backfilling or substituting the nearest date. Validate the entire batch first.
        if missing and prices:
            raise ValueError('No exact-date bar for: ' + ', '.join(missing) + '; no prices written')
        status = 'success' if prices else 'no_data'
        note = ('Exact-date bars fetched; dry run, no database writes' if dry_run else 'Exact-date bars loaded') if prices else 'No bars for requested date (possibly market closed)'
        if db and prices:
            db.call('poc_securities', method='POST', data=securities,
                    query={'on_conflict': 'yahoo_symbol'}, upsert=True)
            saved = db.call('poc_daily_prices', method='POST', data=prices,
                            query={'on_conflict': 'yahoo_symbol,price_date,source'}, upsert=True)
            written = len(saved)
            if written != len(prices):
                raise ValueError('Supabase returned an unexpected write count')
            verified = db.call('poc_daily_prices', query={
                'run_id': f'eq.{run_id}', 'select': 'yahoo_symbol,price_date,close,run_id'})
            if {r['yahoo_symbol'] for r in verified} != set(symbols) or any(r['price_date'] != target.isoformat() for r in verified):
                raise ValueError('Supabase read-back did not match requested symbols/date')
            expected = {r['yahoo_symbol']: r['close'] for r in prices}
            if any(not math.isclose(float(r['close']), expected[r['yahoo_symbol']], rel_tol=1e-12) for r in verified):
                raise ValueError('Supabase read-back close prices did not match fetched prices')
        if db:
            db.call('poc_price_runs', method='PATCH', query={'id': f'eq.{run_id}'},
                    data={'status': status, 'rows_written': written, 'note': note, 'finished_at': now()})
        report = {'run_id': run_id, 'price_date': target.isoformat(), 'dry_run': dry_run,
                  'status': status, 'rows_written': written, 'bars_fetched': len(prices), 'note': note}
        if output:
            Path(output).write_text(json.dumps({'report': report, 'securities': securities, 'prices': prices}, indent=2) + '\n')
        print(json.dumps(report))
        return 0 if prices else 2
    except Exception as exc:
        if db:
            try:
                db.call('poc_price_runs', method='PATCH', query={'id': f'eq.{run_id}'}, data={
                    'status': 'failed', 'rows_written': written,
                    'note': str(exc)[:500], 'finished_at': now()})
            except Exception:
                print('Could not finalize run log; inspect running attempts in Supabase.', file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True, type=date.fromisoformat)
    parser.add_argument('--symbols', nargs='+', default=['AAPL', 'MSFT', 'SPY'])
    parser.add_argument('--dry-run', action='store_true', help='Fetch real Yahoo bars without connecting to Supabase')
    parser.add_argument('--output', help='Optional local JSON evidence file')
    args = parser.parse_args()
    symbols = list(dict.fromkeys(s.upper().strip() for s in args.symbols))
    if not 1 <= len(symbols) <= 5 or any(not re.fullmatch(r'[A-Z0-9^][A-Z0-9.^=\-]{0,31}', s) for s in symbols):
        parser.error('Provide 1–5 distinct Yahoo symbols')
    if args.date >= datetime.now(NY).date():
        parser.error('Choose a past date so this demo never stores an incomplete current session')
    try:
        return run(args.date, symbols, dry_run=args.dry_run, output=args.output)
    except Exception as exc:
        print(f'Pricing run failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
