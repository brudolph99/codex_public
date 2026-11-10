"""Fetch one daily US equity bar per enabled Supabase watchlist symbol."""
import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg

SOURCE = 'alpha_vantage'
NY = ZoneInfo('America/New_York')
PRICE_FIELDS = ('1. open', '2. high', '3. low', '4. close')

UPSERT_PRICE = """
    insert into public.poc_daily_prices (
        yahoo_symbol, price_date, source, currency, open, high, low, close,
        volume, fetched_at, run_id
    ) values (%s, %s, %s, 'USD', %s, %s, %s, %s, %s, now(), %s)
    on conflict (yahoo_symbol, price_date, source) do update set
        currency = excluded.currency, open = excluded.open, high = excluded.high,
        low = excluded.low, close = excluded.close, volume = excluded.volume,
        adjusted_close = excluded.adjusted_close, fetched_at = excluded.fetched_at,
        run_id = excluded.run_id
"""


class RunError(Exception):
    """An operational error whose message is safe to log."""


def fetch_bar(symbol, target, api_key):
    query = urlencode({
        'function': 'TIME_SERIES_DAILY', 'symbol': symbol,
        'apikey': api_key,
    })
    try:
        with urlopen(f'https://www.alphavantage.co/query?{query}', timeout=20) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RunError(f'{symbol}: provider returned HTTP {exc.code}') from None
    except (URLError, TimeoutError, ValueError):
        raise RunError(f'{symbol}: provider response unavailable or unreadable') from None

    try:
        series = payload['Time Series (Daily)']
        if payload['Meta Data']['2. Symbol'] != symbol or not series:
            raise ValueError
        if target < min(series):
            raise RunError(f'{symbol}: requested date predates the compact feed')
        if target not in series:
            return None
        bar = series[target]
        open_, high, low, close = (Decimal(bar[field]) for field in PRICE_FIELDS)
        volume = int(bar['5. volume'])
        if not all(p.is_finite() and p > 0 for p in (open_, high, low, close)):
            raise ValueError
        if volume < 0 or low > min(open_, close) or high < max(open_, close):
            raise ValueError
        return open_, high, low, close, volume
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise RunError(f'{symbol}: provider returned no usable series or an invalid bar') from None


def finish_run(db, run_id, status, rows, note):
    result = db.execute(
        """
        update public.poc_price_runs
        set status = %s, rows_written = %s, note = %s, finished_at = now()
        where id = %s and status = 'running'
        """,
        (status, rows, note, run_id),
    )
    if result.rowcount != 1:
        raise RunError('Could not finalize the run record')


def run(db, target, selected, api_key):
    run_id = uuid4()
    symbols = []
    selection_error = None
    with db.transaction():
        enabled = [row[0] for row in db.execute(
            'select yahoo_symbol from public.poc_securities where enabled order by yahoo_symbol'
        )]
        symbols = sorted(set(selected)) if selected else enabled
        if not symbols or not set(symbols).issubset(enabled):
            selection_error = 'Select at least one enabled watchlist symbol'
        elif api_key == 'demo' and symbols != ['IBM']:
            selection_error = 'The provider demo key supports only IBM. Use --symbol IBM.'
        db.execute(
            """
            insert into public.poc_price_runs (id, price_date, requested_symbols, source, status)
            values (%s, %s, %s, %s, 'running')
            """,
            (run_id, target, symbols, SOURCE),
        )

    try:
        if selection_error:
            raise RunError(selection_error)
        rows, missing = [], []
        for symbol in symbols:
            bar = fetch_bar(symbol, target.isoformat(), api_key)
            if bar is None:
                missing.append(symbol)
            else:
                rows.append((symbol, target, SOURCE, *bar, run_id))
        if missing and rows:
            raise RunError('Missing exact-date bars for ' + ', '.join(missing))
        status = 'success' if rows else 'no_data'
        note = 'Exact-date bars loaded' if rows else 'Provider had no bars for the requested date'
        with db.transaction(), db.cursor() as cursor:
            if rows:
                cursor.executemany(UPSERT_PRICE, rows)
                if cursor.rowcount != len(rows):
                    raise RunError('Price write count did not match fetched bars')
            finish_run(db, run_id, status, len(rows), note)
    except (RunError, psycopg.Error) as exc:
        note = str(exc) if isinstance(exc, RunError) else f'Database write failed ({exc.sqlstate or "connection error"})'
        try:
            with db.transaction():
                finish_run(db, run_id, 'failed', 0, note)
        except (RunError, psycopg.Error):
            print(f'Could not finalize run {run_id}', file=sys.stderr)
        raise RunError(f'Run {run_id}: {note}') from None

    print(json.dumps({
        'run_id': str(run_id), 'date': target.isoformat(), 'source': SOURCE,
        'status': status, 'symbols': symbols, 'rows_written': len(rows),
    }))


def main():
    previous_day = datetime.now(NY).date() - timedelta(days=1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', type=date.fromisoformat, default=previous_day)
    parser.add_argument('--symbol', action='append', help='Limit the run to an enabled symbol. Repeat to select more.')
    args = parser.parse_args()
    if args.date > previous_day:
        parser.error('Choose a completed US market date')
    api_key = os.environ.get('ALPHA_VANTAGE_API_KEY')
    if not api_key or not os.environ.get('PGSERVICEFILE'):
        parser.error('Set ALPHA_VANTAGE_API_KEY and PGSERVICEFILE in the runner environment')
    try:
        with psycopg.connect('service=market-poc', autocommit=True, connect_timeout=8) as db:
            run(db, args.date, args.symbol, api_key)
    except (RunError, psycopg.Error) as exc:
        message = str(exc) if isinstance(exc, RunError) else f'Database operation failed ({exc.sqlstate or "connection error"})'
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
