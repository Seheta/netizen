# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""Build the YouTube part of the case library: for each case, find the top Indonesian videos
in its date window and pull their most relevant comments into data/library/youtube/<id>.json.

Needs YOUTUBE_API_KEY in netizen/.env (YouTube Data API v3; free, 10,000 quota units/day).
Quota per case ≈ 100 (search) + 1 (video stats) + 1 per 100 comments ≈ 120 units.
Commenter names and channel ids are not stored; only text, likes, replies, and time.

Run (from the netizen/ folder):
  uv run spike/youtube_fetch.py                 all cases in spike/cases.json not yet fetched
  uv run spike/youtube_fetch.py c2_tapera --videos 5 --comments 300 --force
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "data" / "library" / "youtube"
API = "https://www.googleapis.com/youtube/v3"


def load_env() -> None:
    env = ROOT.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def get(client: httpx.Client, path: str, **params) -> dict:
    r = client.get(f"{API}/{path}", params={"key": os.environ["YOUTUBE_API_KEY"], **params})
    if r.status_code != 200:
        reason = r.json().get("error", {}).get("errors", [{}])[0].get("reason", "")
        raise RuntimeError(f"{path} {r.status_code} {reason}")
    return r.json()


def fetch_case(client: httpx.Client, case: dict, n_videos: int, n_comments: int) -> dict:
    found = get(client, "search", part="snippet", q=case["query"], type="video", order="viewCount",
                regionCode="ID", relevanceLanguage="id", maxResults=n_videos,
                publishedAfter=f"{case['since']}T00:00:00Z", publishedBefore=f"{case['until']}T23:59:59Z")
    ids = [it["id"]["videoId"] for it in found.get("items", [])][:n_videos]  # API sometimes returns more
    stats = get(client, "videos", part="snippet,statistics", id=",".join(ids)) if ids else {"items": []}
    videos = []
    for v in stats["items"]:
        s, sn = v["statistics"], v["snippet"]
        comments, token = [], None
        while len(comments) < n_comments:
            try:
                page = get(client, "commentThreads", part="snippet", videoId=v["id"], order="relevance",
                           textFormat="plainText", maxResults=100, **({"pageToken": token} if token else {}))
            except RuntimeError as e:  # comments disabled on this video
                print(f"    {v['id']}: {e}")
                break
            for t in page["items"]:
                c = t["snippet"]["topLevelComment"]["snippet"]
                comments.append({"text": c["textDisplay"], "likes": c["likeCount"],
                                 "replies": t["snippet"]["totalReplyCount"], "published": c["publishedAt"]})
            token = page.get("nextPageToken")
            if not token:
                break
        videos.append({"video_id": v["id"], "title": sn["title"], "channel": sn["channelTitle"],
                       "published": sn["publishedAt"], "description": sn.get("description", "")[:1500], "views": int(s.get("viewCount", 0)),
                       "likes": int(s.get("likeCount", 0)), "comment_count": int(s.get("commentCount", 0)),
                       "comments": comments[:n_comments]})
        print(f"    {v['id']}  {int(s.get('viewCount', 0)):>10,} views  {len(comments[:n_comments]):>4} comments  {sn['title'][:60]}")
    return {**case, "platform": "youtube", "videos": videos}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--videos", type=int, default=5)
    ap.add_argument("--comments", type=int, default=200, help="per video")
    ap.add_argument("--force", action="store_true", help="refetch cases already saved")
    args = ap.parse_args()
    load_env()
    if not os.environ.get("YOUTUBE_API_KEY"):
        sys.exit("YOUTUBE_API_KEY missing in netizen/.env")
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    if args.ids:
        cases = [c for c in cases if c["id"] in args.ids]
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30) as client:
        for case in cases:
            path = OUT / f"{case['id']}.json"
            if path.exists() and not args.force:
                print(f"skip {case['id']} (exists)")
                continue
            print(f"{case['id']}: '{case['query']}' {case['since']}..{case['until']}")
            data = fetch_case(client, case, args.videos, args.comments)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            n = sum(len(v["comments"]) for v in data["videos"])
            print(f"  -> {path.relative_to(ROOT.parent)}  ({len(data['videos'])} videos, {n} comments)")


if __name__ == "__main__":
    main()
