# Cloud job proof of concept

For the separate Python → Yahoo Finance → Supabase exercise, see
[the pricing demo](pricing_demo/README.md).

Fetch the latest public Python development update from GitHub's Atom feed:

```sh
python3 fetch_headline.py
```

Requires Python 3.10 or newer, with no extra packages or credentials. Each run
prints a JSON record and appends it to `logs/headlines.jsonl`, containing the UTC
check time, headline, source, and article URL. Repeated headlines are intentional:
this demonstrates a scheduled observation, even when the source has not changed.
Network or malformed-feed errors fail the job instead of logging success.

## Hourly job

Once this workflow is pushed to the repository's default branch, GitHub Actions
runs it at minute 17 of each hour (UTC). You can also run **Hourly live update**
manually from the repository's Actions tab. GitHub Actions must be enabled.
Scheduled runs may be delayed and inactive public repositories may have their
schedules disabled after 60 days.

Each run has console output and a downloadable JSON log artifact retained for
30 days. Each hosted run starts fresh, so artifacts are separate observations,
not a permanent combined database. Supabase is unnecessary for this demo.

For the original environment smoke test, run `python3 hello_cloud.py`.
