#!/bin/sh
set -eu

: "${PRICING_POC_HOME:?Set PRICING_POC_HOME to the private runner directory}"
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
set -a
. "$PRICING_POC_HOME/runner.env"
set +a
export PGSERVICEFILE="$PRICING_POC_HOME/pg_service.conf"
export PGPASSFILE="$PRICING_POC_HOME/pgpass"

exec flock -n "$PRICING_POC_HOME/run.lock" \
    "$PRICING_POC_HOME/venv/bin/python" -B "$script_dir/ingest.py" "$@"
