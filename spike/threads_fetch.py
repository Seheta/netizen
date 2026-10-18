# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""Fetch public Threads posts by keyword into data/threads_<name>.csv.

Needs THREADS_ACCESS_TOKEN in netizen/.env, from a Meta app with the
`threads_basic` and `threads_keyword_search` permissions. Until Meta approves
`threads_keyword_search` in App Review, the API only searches your own posts.

Examples (from the netizen/ folder):
  uv run spike/threads_fetch.py tapera "tapera" --since 2024-05-28 --until 2024-06-04
  uv run spike/threads_fetch.py ppn12 "PPN 12%" --since 2024-12-18 --until 2024-12-25 --max 300
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / "data"
URL = "https://graph.threads.com/v1.0/keyword_search"
FIELDS = "id,text,media_type,permalink,timestamp,username,has_replies,is_quote_post,is_reply"


def load_env() -> None:
    env = ROOT.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def ts(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="output name, e.g. tapera")
    ap.add_argument("query", help="keyword(s) to search")
    ap.add_argument("--since", help="YYYY-MM-DD (not before 2023-07-05)")
    ap.add_argument("--until", help="YYYY-MM-DD")
    ap.add_argument("--type", default="RECENT", choices=["RECENT", "TOP"])
    ap.add_argument("--max", type=int, default=300)
    args = ap.parse_args()

    load_env()
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    if not token:
        sys.exit("THREADS_ACCESS_TOKEN missing (put it in netizen/.env)")

    params = {"q": args.query, "search_type": args.type, "fields": FIELDS,
              "limit": 100, "access_token": token}
    if args.since:
        params["since"] = ts(args.since)
    if args.until:
        params["until"] = ts(args.until)

    rows, url = [], URL
    with httpx.Client(timeout=30) as client:
        while url and len(rows) < args.max:
            r = client.get(url, params=params)
            if r.status_code != 200:
                sys.exit(f"Threads API error {r.status_code}: {r.text[:300]}")
            body = r.json()
            rows += [p for p in body.get("data", []) if p.get("text")]
            url = body.get("paging", {}).get("next")
            params = None  # the next URL already carries every parameter

    rows = rows[: args.max]
    if not rows:
        sys.exit("No posts returned. Without threads_keyword_search approval only your own posts are searched; "
                 "sensitive keywords also return nothing.")
    DATA.mkdir(exist_ok=True)
    out = DATA / f"threads_{args.name}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS.split(","), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} posts -> {out}")


if __name__ == "__main__":
    main()
