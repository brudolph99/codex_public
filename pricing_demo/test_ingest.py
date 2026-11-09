"""Synthetic fixtures for behavior checks; never written to the live database."""
import copy
from datetime import date, datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
import ingest

TARGET = date(2026, 11, 6)


def fixture():
    return {'chart': {'error': None, 'result': [{
        'meta': {'symbol': 'AAPL', 'exchangeTimezoneName': 'America/New_York',
                 'currency': 'USD', 'exchangeName': 'NMS', 'instrumentType': 'EQUITY'},
        'timestamp': [int(datetime(2026, 11, 6, 9, 30, tzinfo=ZoneInfo('America/New_York')).timestamp())],
        'indicators': {'quote': [{'open': [100.0], 'high': [102.0], 'low': [99.0],
                                  'close': [101.0], 'volume': [1000]}],
                       'adjclose': [{'adjclose': [100.5]}]}}]}}


class ParseTests(unittest.TestCase):
    def test_exact_date_currency_and_adjusted_price(self):
        security, price = ingest.parse_yahoo(fixture(), 'AAPL', TARGET, 'test-run')
        self.assertEqual(price['price_date'], '2026-11-06')
        self.assertEqual(price['currency'], 'USD')
        self.assertEqual(price['close'], 101)
        self.assertEqual(price['adjusted_close'], 100.5)
        self.assertIsNone(security['display_name'])

    def test_does_not_substitute_friday_for_weekend(self):
        self.assertIsNone(ingest.parse_yahoo(fixture(), 'AAPL', date(2026, 11, 7), 'test'))

    def test_uses_exchange_local_date(self):
        data = fixture()
        result = data['chart']['result'][0]
        result['meta']['exchangeTimezoneName'] = 'Asia/Tokyo'
        result['timestamp'] = [int(datetime(2026, 11, 6, 0, 30, tzinfo=ZoneInfo('Asia/Tokyo')).timestamp())]
        self.assertIsNotNone(ingest.parse_yahoo(data, 'AAPL', TARGET, 'test'))

    def test_rejects_invalid_bar(self):
        for value in (None, float('nan'), float('inf'), -1):
            with self.subTest(value=value):
                data = fixture()
                data['chart']['result'][0]['indicators']['quote'][0]['close'] = [value]
                with self.assertRaises(ValueError):
                    ingest.parse_yahoo(data, 'AAPL', TARGET, 'test')

    def test_rejects_provider_error_and_symbol_mismatch(self):
        for data in ({'chart': {'error': {'code': 'Not Found'}}}, fixture()):
            with self.assertRaises(ValueError):
                ingest.parse_yahoo(data, 'MSFT', TARGET, 'test')


class FakeDB:
    def __init__(self, fail_prices=False):
        self.calls = []
        self.prices = {}
        self.fail_prices = fail_prices

    def call(self, table, *, method='GET', data=None, query=None, upsert=False):
        self.calls.append((table, method, data))
        if table == 'poc_daily_prices':
            if method == 'POST':
                if self.fail_prices:
                    raise RuntimeError('Simulated write failure')
                for row in data:
                    self.prices[(row['yahoo_symbol'], row['price_date'], row['source'])] = copy.deepcopy(row)
                return data
            return [r for r in self.prices.values() if 'eq.' + r['run_id'] == query['run_id']]
        return [data]


class RunTests(unittest.TestCase):
    def test_rerun_upserts_and_reads_back(self):
        db = FakeDB()
        with patch.object(ingest, 'Supabase', return_value=db), patch.object(ingest, 'fetch_yahoo', return_value=fixture()):
            self.assertEqual(ingest.run(TARGET, ['AAPL']), 0)
            self.assertEqual(ingest.run(TARGET, ['AAPL']), 0)
        self.assertEqual(len(db.prices), 1)
        self.assertEqual(db.calls[-1][2]['status'], 'success')
        self.assertEqual(db.calls[-1][2]['rows_written'], 1)

    def test_failed_write_does_not_report_success(self):
        db = FakeDB(fail_prices=True)
        with patch.object(ingest, 'Supabase', return_value=db), patch.object(ingest, 'fetch_yahoo', return_value=fixture()):
            with self.assertRaises(RuntimeError):
                ingest.run(TARGET, ['AAPL'])
        self.assertEqual(db.calls[-1][2]['status'], 'failed')
        self.assertEqual(db.calls[-1][2]['rows_written'], 0)

    def test_mixed_missing_data_does_not_write_prices(self):
        db = FakeDB()
        def fetch(symbol, target):
            data = fixture()
            if symbol == 'MSFT':
                data['chart']['result'][0]['meta']['symbol'] = 'MSFT'
                data['chart']['result'][0]['timestamp'] = []
            return data
        with patch.object(ingest, 'Supabase', return_value=db), patch.object(ingest, 'fetch_yahoo', side_effect=fetch):
            with self.assertRaises(ValueError):
                ingest.run(TARGET, ['AAPL', 'MSFT'])
        self.assertFalse(db.prices)
        self.assertEqual(db.calls[-1][2]['status'], 'failed')

    def test_closed_date_logged_as_no_data(self):
        db = FakeDB()
        with patch.object(ingest, 'Supabase', return_value=db), patch.object(ingest, 'fetch_yahoo', return_value=fixture()):
            self.assertEqual(ingest.run(date(2026, 11, 7), ['AAPL']), 2)
        self.assertEqual(db.calls[-1][2]['status'], 'no_data')
        self.assertFalse(db.prices)

    def test_dry_run_never_initializes_database(self):
        with patch.object(ingest, 'Supabase') as db, patch.object(ingest, 'fetch_yahoo', return_value=fixture()):
            ingest.run(TARGET, ['AAPL'], dry_run=True)
            db.assert_not_called()


if __name__ == '__main__':
    unittest.main()
