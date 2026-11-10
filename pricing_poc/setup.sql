-- Apply once to the existing three proof-of-concept tables as a database admin.
alter table public.poc_securities
  add column enabled boolean not null default true;

alter table public.poc_price_runs
  drop constraint poc_price_runs_source_check,
  add constraint poc_price_runs_source_check
    check (source in ('yahoo_finance', 'alpha_vantage'));

alter table public.poc_daily_prices
  drop constraint poc_daily_prices_source_check,
  add constraint poc_daily_prices_source_check
    check (source in ('yahoo_finance', 'alpha_vantage'));

-- The operator provisions a password separately.
create role poc_price_runner login connection limit 2;
grant usage on schema public to poc_price_runner;
grant select on public.poc_securities to poc_price_runner;
grant select, insert, update on public.poc_daily_prices, public.poc_price_runs
  to poc_price_runner;

create policy poc_runner_read_watchlist on public.poc_securities
  for select to poc_price_runner using (true);

create policy poc_runner_prices on public.poc_daily_prices
  for all to poc_price_runner
  using (source = 'alpha_vantage') with check (source = 'alpha_vantage');

create policy poc_runner_logs on public.poc_price_runs
  for all to poc_price_runner
  using (source = 'alpha_vantage') with check (source = 'alpha_vantage');

insert into public.poc_securities (yahoo_symbol, display_name) values
  ('AAPL', 'Apple'), ('AMZN', 'Amazon'), ('COST', 'Costco'),
  ('GOOGL', 'Alphabet Class A'), ('IBM', 'IBM'), ('JNJ', 'Johnson & Johnson'),
  ('JPM', 'JPMorgan Chase'), ('META', 'Meta Platforms'), ('MSFT', 'Microsoft'),
  ('NVDA', 'NVIDIA'), ('PG', 'Procter & Gamble'), ('XOM', 'Exxon Mobil')
on conflict (yahoo_symbol) do nothing;
