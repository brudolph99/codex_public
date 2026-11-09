# One-date Python pricing demo

Python does the fetching, validation, loading, and verification. Supabase stores
the data and run history. No Edge Functions, database jobs, historical backfill,
or changes to existing `fin_*` tables are involved.

## Three tables

| Table | Purpose |
| --- | --- |
| `poc_securities` | Yahoo symbol, optional display name, exchange, instrument type |
| `poc_daily_prices` | One daily OHLC/adjusted-close/volume observation per symbol/date/source, plus currency, fetch time, and run ID |
| `poc_price_runs` | Requested date/symbols, start/end time, outcome, confirmed write count, note |

`schema.sql` was applied to project `vcncmuvkdtafbqicudsr` on November 9, 2026.
It is a record of the initial schema, not a script to rerun on this project.
All three tables have RLS enabled and deny `anon`/`authenticated` access.
The trusted backend uses a Supabase secret API key. There are intentionally no
public row policies. The advisor's informational "RLS Enabled No Policy" notice
is expected for this backend-only model:
https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy

This is a provider-symbol lookup, not a legal security master. No ISIN/CUSIP is
invented. Symbols can change or be reused; permanent identifiers and historical
identity mapping belong in a later phase. Yahoo daily OHLC is vendor history
that can be adjusted for splits; adjusted close also reflects vendor dividend
adjustments. These are not raw as-traded or historical point-in-time prices.
Quote currency comes from Yahoo; the script does not assume USD.

## Run in Cloud or locally

Requires Python 3.11+ with timezone data; no third-party Python packages.
Set these variables through your runner's settings (never paste the key in chat
or commit it):

- `SUPABASE_URL`: `https://vcncmuvkdtafbqicudsr.supabase.co`
- `SUPABASE_SECRET_KEY`: a backend secret key from Supabase Settings → API Keys.
  This privileged key bypasses RLS; keep it in a trusted runner's secret store.

The Python loader also accepts lowercase `supabase_url` and
`supabase_secret_key`, matching personal Cloud vault variable names. Saving a
vault item alone does not establish that it is attached to the running Cloud
environment; confirm its environment binding and network permissions are applied.

Allow outbound HTTPS to `query1.finance.yahoo.com` and
`vcncmuvkdtafbqicudsr.supabase.co` in Cloud network settings.

From the repository root:

```sh
python pricing_demo/ingest.py --date 2026-11-06 --symbols AAPL MSFT SPY --output /tmp/pricing-result.json
```

For a real Yahoo fetch without any Supabase connection:

```sh
python pricing_demo/ingest.py --date 2026-11-06 --symbols AAPL MSFT SPY --dry-run
```

The date is required and must be earlier than today in New York. The script
accepts at most five distinct symbols. It selects the exact exchange-local
date, never the nearest trading day. A closed date is recorded as `no_data`
(exit 2); other failures exit 1. If only some symbols have bars, no prices are
written and the run fails. All requested bars are validated before loading.

Reruns upsert the same symbol/date/source rows, updating values and provenance,
while adding a new run log. Read-back checks the saved date, symbols, and close
prices before success. Run history persists, but prior price revisions do not.

The security upsert, price batch upsert, and log update are separate requests.
An interrupted run can leave securities without prices or a `running` run log.
A lost write response can leave committed prices with an unconfirmed write
count. Recheck the database and rerun the exact date/symbols to recover; there
are no automatic write retries. This is a small proof of concept, not a full
transactional ingestion service. Yahoo's public chart endpoint is unofficial
and can change or rate-limit; provider failures must be resolved rather than
treated as successful ingestion.

## Run on GitHub Actions

The manual workflow is `.github/workflows/pricing-demo.yml`. To use it, publish
the code to the repository's default branch, enable Actions, add repository
variable `SUPABASE_URL` and repository secret `SUPABASE_SECRET_KEY`, then run
**Python pricing demo** with a past date and up to five space-separated symbols.
It tests the loader, runs it, and retains a JSON result artifact for seven days.
It has no schedule: this demo only runs when explicitly dispatched.

## Verification

```sh
python -m unittest discover -s pricing_demo -v
```

Ten offline tests cover exchange-local dates, no date substitution, invalid
prices, provider errors, idempotent writes, read-back, missing data, failures,
and dry-run behavior. Their fixtures are synthetic and never sent to Supabase.

At creation time the live tables were verified in Supabase, but live Python
ingestion was blocked: Cloud network policy denied Yahoo and no backend key was
configured. No live prices or simulated data have been loaded. A passing unit
test is not evidence of a completed end-to-end load.

After a live run, inspect the data in Supabase:

```sql
select * from public.poc_price_runs order by started_at desc limit 10;
select yahoo_symbol, price_date, currency, close, run_id
from public.poc_daily_prices order by price_date desc, yahoo_symbol;
```
