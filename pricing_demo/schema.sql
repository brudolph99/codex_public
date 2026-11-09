-- Small, isolated Python ingestion proof of concept. No existing fin_* tables changed.
create table public.poc_securities (
  yahoo_symbol text primary key check (length(yahoo_symbol) between 1 and 32),
  display_name text,
  exchange text,
  instrument_type text,
  updated_at timestamptz not null default now()
);

create table public.poc_price_runs (
  id uuid primary key,
  price_date date not null,
  requested_symbols text[] not null,
  source text not null default 'yahoo_finance' check (source = 'yahoo_finance'),
  status text not null check (status in ('running', 'success', 'no_data', 'failed')),
  rows_written integer not null default 0 check (rows_written >= 0),
  note text,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create table public.poc_daily_prices (
  yahoo_symbol text not null references public.poc_securities(yahoo_symbol),
  price_date date not null,
  source text not null check (source = 'yahoo_finance'),
  currency text not null,
  open numeric not null check (open > 0),
  high numeric not null check (high > 0),
  low numeric not null check (low > 0),
  close numeric not null check (close > 0),
  adjusted_close numeric check (adjusted_close > 0),
  volume bigint check (volume >= 0),
  fetched_at timestamptz not null,
  run_id uuid not null references public.poc_price_runs(id),
  primary key (yahoo_symbol, price_date, source),
  check (low <= least(open, close) and high >= greatest(open, close))
);
create index poc_daily_prices_date_idx on public.poc_daily_prices(price_date);
create index poc_daily_prices_run_idx on public.poc_daily_prices(run_id);

comment on table public.poc_securities is 'Demo provider-symbol lookup only. A Yahoo symbol is not a permanent legal security identifier; no inferred ISIN or CUSIP.';
comment on table public.poc_daily_prices is 'Yahoo daily vendor OHLC (split-adjusted history); adjusted_close additionally reflects vendor dividend adjustments. Not an as-traded or point-in-time archive.';
comment on table public.poc_price_runs is 'Python ingestion attempts; one date and at most 5 symbols. A terminated process can leave running status; do not interpret it as success.';

alter table public.poc_securities enable row level security;
alter table public.poc_price_runs enable row level security;
alter table public.poc_daily_prices enable row level security;
revoke all on public.poc_securities, public.poc_price_runs, public.poc_daily_prices from anon, authenticated;
grant select, insert, update on public.poc_securities, public.poc_price_runs, public.poc_daily_prices to service_role;
