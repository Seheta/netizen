# /// script
# requires-python = ">=3.11"
# dependencies = ["typesafe-sdk>=0.7"]
# ///
"""Label the stance of every comment in the case library with Jev, and print each case's mix.

For each comment Jev answers two questions: is it about the case subject at all (spam, jokes about
something else, and "first!" are not), and if so, how does the author feel about the subject.
Mixes are given over on-topic comments, both per comment and weighted by comment likes
(what a reader scrolling the top comments sees).

Run (from the netizen/ folder):
  uv run spike/library_label.py                  all fetched cases not yet labeled
  uv run spike/library_label.py c2_tapera --force
Output: data/library/youtube_labels/<id>.json
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, Noul, Score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spike import PRICE_PER_MTOK, STANCE_LEVELS, bucket, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parent
LIB = ROOT.parent / "data" / "library"
BATCH = 40
KEYS = ("negative", "neutral", "positive")


async def label_video(client, sem, case: dict, video: dict) -> int:
    subject = case["subject"]
    comments = video["comments"]

    async def one(start: int) -> int:
        chunk = comments[start:start + BATCH]
        state = {"context": f"YouTube comments (Indonesia) under the video titled {video['title']!r} "
                            f"by channel {video['channel']!r}.",
                 "comments": {f"k{i:03d}": c["text"][:600] for i, c in enumerate(chunk)}}
        qs = {}
        for i in range(len(chunk)):
            ref = f"`comments.k{i:03d}`"
            qs[f"on{i:03d}"] = Noul(instructions=f"Is comment {ref} a reaction to the issue the video is about "
                                                 f"({subject}), including complaints or praise about closely "
                                                 f"related things (e.g. taxes in general, officials, the people in "
                                                 f"the video)? Spam, ads, greetings, and unrelated chatter are not.")
            qs[f"st{i:03d}"] = Score(instructions=f"How does the author of comment {ref} feel about {subject}? "
                                                  f"Read sarcasm, irony, and slang for what they really mean. "
                                                  f"Purely informational comments or questions are neutral.",
                                     criteria=STANCE_LEVELS)
        async with sem:
            r = await client.system_one(state=state, questions=qs)
        for i, c in enumerate(chunk):
            on, st = r.answers[f"on{i:03d}"], r.answers[f"st{i:03d}"]
            c["on_topic"] = round(on.noul, 3)
            c["stance"] = bucket(max(st.probabilities, key=st.probabilities.get))
            c["score"] = round(st.score - 2, 3)
        return r.usage.input_tokens

    return sum(await asyncio.gather(*(one(s) for s in range(0, len(comments), BATCH))))


def mix(comments: list[dict], weight) -> dict[str, float]:
    tot = Counter()
    for c in comments:
        tot[c["stance"]] += weight(c)
    s = sum(tot.values()) or 1
    return {k: tot[k] / s for k in KEYS}


def fmt(m: dict[str, float]) -> str:
    return "  ".join(f"{k[:3]} {m[k]:5.1%}" for k in KEYS)


def report(data: dict) -> None:
    allc = [c for v in data["videos"] for c in v["comments"]]
    on = [c for c in allc if c["on_topic"] >= 0.5]
    print(f"\n{data['id']}  ({data['category']})  {len(allc)} comments, {len(on) / max(len(allc), 1):.0%} on topic")
    print(f"  per comment   : {fmt(mix(on, lambda c: 1))}")
    print(f"  like-weighted : {fmt(mix(on, lambda c: 1 + c['likes']))}")
    for v in data["videos"]:
        von = [c for c in v["comments"] if c["on_topic"] >= 0.5]
        if von:
            print(f"    {fmt(mix(von, lambda c: 1))}  n={len(von):3}  {v['title'][:55]}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    load_env()
    cases = {c["id"]: c for c in json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))}
    src, dst = LIB / "youtube", LIB / "youtube_labels"
    dst.mkdir(parents=True, exist_ok=True)
    ids = args.ids or [p.stem for p in sorted(src.glob("*.json"))]
    client, sem, tokens = AsyncTypeSafeClient(), asyncio.Semaphore(6), 0
    for cid in ids:
        out = dst / f"{cid}.json"
        if out.exists() and not args.force:
            report(json.loads(out.read_text(encoding="utf-8")))
            continue
        data = json.loads((src / f"{cid}.json").read_text(encoding="utf-8"))
        case = {**data, **cases[cid]}  # subject may have been added after fetching
        tokens += sum(await asyncio.gather(*(label_video(client, sem, case, v) for v in data["videos"])))
        out.write_text(json.dumps({**data, "subject": case["subject"]}, ensure_ascii=False, indent=1), encoding="utf-8")
        report(data)
    print(f"\nJev input tokens: {tokens:,}  ≈ ${tokens / 1e6 * PRICE_PER_MTOK:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
