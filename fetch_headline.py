"""Fetch one live update and append a JSON record. No dependencies required."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

FEED_URL = "https://github.com/python/cpython/commits/main.atom"
ATOM = "{http://www.w3.org/2005/Atom}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("logs/headlines.jsonl"))
    args = parser.parse_args()
    request = Request(FEED_URL, headers={"User-Agent": "cloud-job-demo/1.0"})
    with urlopen(request, timeout=30) as response:
        feed = ET.fromstring(response.read())
    entry = feed.find(f"{ATOM}entry")
    if entry is None:
        raise ValueError("Feed contained no entries")
    title = " ".join(entry.findtext(f"{ATOM}title", "").split())
    link = entry.find(f"{ATOM}link[@rel='alternate']")
    if not title or link is None or not link.get("href"):
        raise ValueError("Latest entry is missing its title or URL")
    record = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": FEED_URL,
        "headline": title,
        "url": link.get("href"),
    }
    line = json.dumps(record, ensure_ascii=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as log:
        log.write(line + "\n")
    print(line)


if __name__ == "__main__":
    main()
