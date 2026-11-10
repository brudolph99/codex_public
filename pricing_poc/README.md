# Daily prices proof of concept

The Digital Ocean runner reads enabled US equity symbols from `poc_securities`,
fetches one completed market date from Alpha Vantage, and upserts raw daily
OHLCV into `poc_daily_prices`. `poc_price_runs` records each attempt, including
the requested symbols and outcome. Price upserts and successful run completion
commit together. Repeating a date updates its price rows and adds a run record.
Prices are in USD and carry their provider and fetch time.

`setup.sql` extends the existing Supabase proof-of-concept tables and seeds
12 symbols. Apply it once after the [original demo schema](https://github.com/brudolph99/codex_public/blob/1630819200bfeb168463ce2a5b7733fc9c89bda2/pricing_demo/schema.sql)
when setting up another environment. The `yahoo_symbol` column keeps its original name. Use US common
stock symbols shared by both providers. Change the watchlist with the
`enabled` field in Supabase. The worker can read the watchlist and write its
own provider's prices and runs. It uses a dedicated Postgres login.

## Run on the server

1. Set `PRICING_POC_HOME` to a private directory outside the Git checkout.
   Set its permissions to `700`. Create a Python 3.12 virtual environment
   there as `venv` and install the locked dependencies on x86-64 Linux.

   ```sh
   python3 -m venv "$PRICING_POC_HOME/venv"
   "$PRICING_POC_HOME/venv/bin/python" -m pip install --require-hashes -r pricing_poc/requirements.txt
   ```

2. Provision the `poc_price_runner` password separately from SQL migrations.
   In `pg_service.conf`, configure a `[market-poc]` service with the
   Supabase Session pooler host from the project's Connect dialog, port
   `5432`, `dbname=postgres`, `user=poc_price_runner.<project-ref>`,
   `sslmode=verify-full` and `sslrootcert` set to the absolute path of the
   Supabase CA certificate. Store the password in
   `pgpass` using libpq's `host:port:database:user:password` format.
   Set `pgpass` and `runner.env` to mode `600`.
3. Use an empty `runner.env` for the public demo. The demo key
   supports the IBM smoke test only.

   ```sh
   ALPHA_VANTAGE_API_KEY=demo pricing_poc/run.sh --symbol IBM
   ```

   Supply `--date YYYY-MM-DD` to rerun a completed date in the compact
   feed. Set `ALPHA_VANTAGE_API_KEY` in `runner.env` for a full run.
   Without a symbol override, the runner loads the whole enabled watchlist. It defaults to the previous date
   in America/New_York.

## Schedule

After a full watchlist run succeeds, install a cron entry on the server
using absolute paths for the private runner directory and Git checkout.
The server schedule below assumes UTC. Tuesday through Saturday at 11:00 UTC
targets the prior US weekday, after its close. A market holiday with
no returned bars is recorded as `no_data`.

```cron
0 11 * * 2-6 PRICING_POC_HOME=/absolute/private/runner /absolute/git/checkout/pricing_poc/run.sh >>/absolute/private/runner/cron.log 2>&1
```

Deploy an approved Git revision to the runner checkout when updating the job.
