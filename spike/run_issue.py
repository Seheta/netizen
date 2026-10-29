# /// script
# requires-python = ">=3.11"
# dependencies = ["typesafe-sdk>=0.7.5"]
# ///
"""End-to-end workflow for a new issue or draft post:

1. Retrieve: Jev rates how similar the new post is to each case in the library and shows the
   closest cases with their real comment mix, as anchors (or flags that none is close).
2. Audience: Jev rates how well each general persona, each interest segment
   (interest_segments.json) and each segment variant (variants.json) fits the post's first circle —
   people who follow or search this topic, or the brand's stated target (--target). A segment joins
   the simulation with all its variants when any of them fits; the segment's weight is split
   between its core persona and its variants by their `share`.
3. Simulate once (rounds.py: round 1 + influencer round 2) per platform, then read the result
   under three reach scenarios:
     niche   only the first circle (weights × fit³), no influencer pickup
     ramai   spreads to interest-adjacent feeds (weights × fit), influencers at 30% of their pickup
     viral   whole platform audience (base weights), influencers at full pickup
   Reach is a scenario dial, not a forecast: we do not model the platform's algorithm.

Run (from the netizen/ folder):
  uv run spike/run_issue.py --text "..." [--subject "..."] [--target "..."] [--platforms Instagram,TikTok]
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, Image, Score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rounds import (  # noqa: E402
    INFLUENCER_SIM_FIELDS, MIN_POST_P, combine, dist, fmt_mix, public, round1, round2, take_text, tokens_of,
)
from spike import PRICE_PER_MTOK, SIM_FIELDS, audience_weight, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parent
LABELS = ROOT.parent / "data" / "library" / "youtube_labels"
KEYS = ("negative", "neutral", "positive")
SIMILARITY = [
    "Unrelated: different topic, different people affected, different kind of reaction",
    "Distant: shares only a broad theme",
    "Somewhat similar: related topic or a similar kind of reaction, but different audience or stakes",
    "Similar: same kind of topic, audience, and stakes",
    "Very similar: practically the same kind of issue",
]
ANCHOR_MIN = 2.5        # best similarity below this: no usable anchor
FIT = [
    "Would almost never come across it: outside their interests and circles",
    "Might see it by chance",
    "Plausibly in the audience: adjacent interest",
    "Likely in the audience: follows or searches this kind of topic",
    "Core audience: exactly who this post is made for and reaches first",
]
SEGMENT_MIN_FIT = 0.5   # segments whose best member fits below this (0..1) are not simulated
MAX_SEGMENTS = 6
SCENARIOS = {  # name: (fit exponent for audience weights, influencer pickup scale)
    "niche": (3, 0.0),
    "ramai": (1, 0.3),
    "viral": (0, 1.0),
}


def segment_families() -> dict[str, list[dict]]:
    """Each interest segment with its variants; a variant inherits the parent's fields it does not set."""
    segments = json.loads((ROOT / "interest_segments.json").read_text(encoding="utf-8"))
    variants = json.loads((ROOT / "variants.json").read_text(encoding="utf-8"))
    fams = {}
    for seg in segments:
        kids = [{**seg, **v, "weight": seg["weight"] * v["share"]} for v in variants if v["parent"] == seg["id"]]
        core = {**seg, "weight": seg["weight"] * (1 - sum(v["share"] for v in kids))}
        fams[seg["id"]] = [core, *kids]
    return fams


def library() -> list[dict]:
    cases = []
    for path in sorted(LABELS.glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        on = [c for v in d["videos"] for c in v["comments"] if c["on_topic"] >= 0.5]
        cnt = Counter(c["stance"] for c in on)
        cases.append({"id": d["id"], "category": d["category"], "subject": d["subject"],
                      "video_titles": [v["title"] for v in d["videos"]],
                      "top_comments": [c["text"][:200] for c in sorted(on, key=lambda c: -c["likes"])[:5]],
                      "mix": {k: cnt[k] / (len(on) or 1) for k in KEYS}, "n": len(on)})
    return cases


async def retrieve(client, post, cases: list[dict]) -> tuple[list[tuple[float, dict]], int]:
    state = {"new_post": post,
             "library": {c["id"]: {k: c[k] for k in ("category", "subject", "video_titles", "top_comments")}
                         for c in cases}}
    qs = {c["id"]: Score(instructions=f"How similar is `new_post` to the past case `library.{c['id']}` in what "
                                      f"Indonesian netizens would react to: the topic, who is affected, the stakes, and "
                                      f"the tone of the reaction it invites?", criteria=SIMILARITY)
          for c in cases}
    r = await client.system_one(state=state, questions=qs)
    return sorted(((r.answers[c["id"]].score, c) for c in cases), key=lambda x: -x[0]), r.usage.input_tokens


async def audience_fit(client, post, target: str, people: list[dict], messenger: str = "", earlier=None) -> tuple[dict[str, float], int]:
    state = {"post": post, "people": {p["id"]: public(p, SIM_FIELDS) for p in people}}
    who = "the people who follow this kind of account or topic, or search for it"
    if earlier:
        state["earlier"] = earlier
        who = "the people who saw or reacted to the earlier posts in `earlier`, plus " + who
    if messenger:
        state["messenger"] = messenger
        who = "the people who follow or like the account or person in `messenger`, or follow or search this topic"
    if target:
        state["target_audience"] = target
        who += ", or the brand's intended target audience in `target_audience`"
    qs = {p["id"]: Score(instructions=f"`post` is published on Indonesian social media and first reaches {who}. "
                                      f"How likely is the Indonesian netizen described in `people.{p['id']}` to be in "
                                      f"that first audience?", criteria=FIT)
          for p in people}
    r = await client.system_one(state=state, questions=qs)
    return {p["id"]: r.answers[p["id"]].score / 4 for p in people}, r.usage.input_tokens


async def simulate(client, post: dict, personas: list[dict], influencers: list[dict]) -> tuple[dict, list, list, int]:
    r1 = await round1(client, post, personas, influencers)
    a = r1["answers"]
    posted = []
    for inf in influencers:
        tp = a[f"{inf['id']}__take"]["probabilities"]
        if 1 - tp.get("ignore", 0) >= MIN_POST_P:
            posted.append((inf, max((k for k in tp if k != "ignore"), key=tp.get), 1 - tp.get("ignore", 0)))
    r2s = await asyncio.gather(*(
        round2(client, post, personas, inf,
               take_text(inf, take, max(dist(a[f"{inf['id']}__stance"]).items(), key=lambda kv: kv[1])[0], False), r1)
        for inf, take, _ in posted))
    return r1, posted, r2s, tokens_of(r1, *r2s)


def scenario(post, personas, influencers, fit, r1, posted, r2s, exp: int, pickup: float) -> dict:
    weights = {p["id"]: audience_weight(p, post["platform"]) * fit[p["id"]] ** exp for p in personas}
    exposures = [(inf, pp * pickup, r2["answers"]) for (inf, _, pp), r2 in zip(posted, r2s)] if pickup else []
    res = combine(post, personas, influencers, r1, exposures, weights)
    readers = sum(r["readers"] for r in res["rows"]) or 1
    res["audience"] = sorted(((r["readers"] / readers, r["label"], r["net2"]) for r in res["rows"]), reverse=True)
    res["pro_r"], res["contra_r"] = res["pro"] / (res["reach2"] or 1), res["contra"] / (res["reach2"] or 1)
    return res


PLATFORMS = ("Instagram", "TikTok", "Threads", "X/Twitter", "YouTube", "Facebook")


IMAGE_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}   # the client needs this header when the post is an image


async def run(client, text: str, subject: str = "", target: str = "", messenger: str = "",
              platforms=PLATFORMS[:4], run_id: str = "issue", image_b64: str = "", earlier: dict | None = None) -> dict:
    """The whole workflow for one post; the CLI report and the web server both read the returned dict.
    image_b64: the post as an image (png/jpg), with `text` as its caption if any. earlier: per platform, the
    account's previous episodes [{"text", "reaction"}] that the personas remember."""
    general = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    fams = segment_families()
    members = [m for fam in fams.values() for m in fam]
    influencers = json.loads((ROOT / "influencers.json").read_text(encoding="utf-8"))
    post_value = text
    if image_b64:
        img = Image.from_base64(image_b64)
        post_value = {"image": img, "caption": text} if text else img
    earlier = earlier or {}
    any_earlier = next((e for e in earlier.values() if e), None)
    (ranked, t_ret), (fit, t_fit) = await asyncio.gather(
        retrieve(client, post_value, library()),
        audience_fit(client, post_value, target, general + members, messenger, any_earlier))
    best = {sid: max(fit[m["id"]] for m in fam) for sid, fam in fams.items()}
    chosen_ids = sorted((sid for sid in fams if best[sid] >= SEGMENT_MIN_FIT), key=lambda sid: -best[sid])[:MAX_SEGMENTS]
    personas = general + [m for sid in chosen_ids for m in fams[sid]]
    posts = [{"id": f"{run_id}_{p.split('/')[0].lower()}", "platform": p, "post": post_value,
              **({"subject": subject} if subject else {}),
              **({"messenger": messenger} if messenger else {}),
              **({"earlier": earlier[p]} if earlier.get(p) else {})} for p in platforms]
    sims = await asyncio.gather(*(simulate(client, p, personas, influencers) for p in posts))
    return {"text": text or "[gambar]", "subject": subject, "target": target, "messenger": messenger, "general": general, "fams": fams,
            "influencers": influencers, "ranked": ranked, "fit": fit, "best": best, "chosen_ids": chosen_ids,
            "personas": personas, "posts": posts, "sims": sims, "tokens": t_ret + t_fit + sum(t for *_, t in sims)}


def web_view(r: dict) -> dict:
    """What the web page draws: per platform and reach scenario, each persona's stop chance, stance and share of readers."""
    out = {"text": r["text"], "tokens": r["tokens"], "segments": r["chosen_ids"],
           "anchors": [{"id": c["id"], "similarity": s, "mix": c["mix"], "n": c["n"]} for s, c in r["ranked"][:3]],
           "platforms": {}}
    for post, (r1, posted, r2s, _) in zip(r["posts"], r["sims"]):
        a = r1["answers"]
        pl = {"virality": a["post__virality"]["score"], "sensitive": a["post__sensitive"]["noul"],
              "influencers": [{"id": i["id"], "label": i["label"], "take": tk, "p": pp} for i, tk, pp in posted], "scenarios": {}}
        for name, (exp, pickup) in SCENARIOS.items():
            res = scenario(post, r["personas"], r["influencers"], r["fit"], r1, posted, r2s, exp, pickup)
            readers = sum(x["readers"] for x in res["rows"]) or 1
            pl["scenarios"][name] = {
                "vocal": res["vocal"], "reach": res["reach2"], "net": res["net2"], "pro": res["pro_r"], "contra": res["contra_r"],
                "personas": [{"id": x["id"], "label": x["label"], "stop": x["stop1"], "net": x["net2"], "share": x["readers"] / readers}
                             for x in res["rows"]]}
        out["platforms"][post["platform"]] = pl
    return out


def save(r: dict, run_id: str) -> Path:
    out = ROOT / "results" / f"issue_{run_id}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"text": r["text"], "subject": r["subject"], "target": r["target"],
                               "retrieval": [{"id": c["id"], "similarity": s} for s, c in r["ranked"]],
                               "fit": r["fit"], "segments": r["chosen_ids"],
                               "runs": [{"post": {**post, "post": post["post"] if isinstance(post["post"], str) else "[gambar]"},
                                         "round1": r1, "posted": [(i["id"], tk, pp) for i, tk, pp in posted],
                                         "round2": list(r2s)} for post, (r1, posted, r2s, _) in zip(r["posts"], r["sims"])]},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--subject", default="")
    ap.add_argument("--target", default="", help="the brand's intended audience, in plain words")
    ap.add_argument("--messenger", default="", help="who posts it: the account, brand, or person, in plain words")
    ap.add_argument("--id", default="issue")
    ap.add_argument("--platforms", default=",".join(PLATFORMS[:4]))
    args = ap.parse_args()
    load_env()
    async with AsyncTypeSafeClient() as client:
        r = await run(client, args.text, args.subject, args.target, args.messenger,
                      [p.strip() for p in args.platforms.split(",")], args.id)
    ranked, fit, fams, general, chosen_ids = r["ranked"], r["fit"], r["fams"], r["general"], r["chosen_ids"]

    print("=== 1. Similar cases in the library (YouTube comments) ===")
    for score, c in ranked[:3]:
        print(f"  {score:4.2f}/4  {c['id']:18} {c['category']:26} real: {fmt_mix(c['mix'])}")
    if ranked[0][0] < ANCHOR_MIN:
        print(f"  !! No usable anchor (best {ranked[0][0]:.2f} < {ANCHOR_MIN}); results below have no real-data reference.")

    print("\n=== 2. Audience fit (0..1) ===")
    for sid in chosen_ids:
        print(f"  segment added  : {sid}  " + ", ".join(f"{m['label'].split(',')[0]} {fit[m['id']]:.2f}" for m in fams[sid]))
    print("  segments left  : " + ", ".join(f"{sid[2:]} {r['best'][sid]:.2f}" for sid in fams if sid not in chosen_ids))
    print("  general        : " + ", ".join(f"{p['label'].split(',')[0]} {fit[p['id']]:.2f}" for p in general))

    print("\n=== 3. Simulation by reach scenario ===")
    for post, (r1, posted, r2s, _) in zip(r["posts"], r["sims"]):
        print(f"\n--- {post['platform']} | influencers who would pick it up if it spreads: "
              + (", ".join(f"{inf['label'].split(' ')[1] if ' ' in inf['label'] else inf['label']}"
                           f"[{take} {pp:.2f}]" for inf, take, pp in posted) or "none"))
        print(f"  {'scenario':8} {'pro':>5} {'contra':>6} {'net':>6}  {'posted content':36}  main readers (share, net)")
        for name, (exp, pickup) in SCENARIOS.items():
            res = scenario(post, r["personas"], r["influencers"], fit, r1, posted, r2s, exp, pickup)
            top = ", ".join(f"{lbl.split(',')[0]} {sh:.0%} {n:+.1f}" for sh, lbl, n in res["audience"][:4])
            print(f"  {name:8} {res['pro_r']:5.0%} {res['contra_r']:6.0%} {res['net2']:+6.2f}  {fmt_mix(res['vocal']):36}  {top}")
    print("\n  pro/contra = share of readers in favor / against; net = mean stance of readers [-2..+2].")

    out = save(r, args.id)
    print(f"\nTotal input tokens {r['tokens']:,} ≈ ${r['tokens'] * PRICE_PER_MTOK / 1e6:.4f}  | raw: {out}")


if __name__ == "__main__":
    asyncio.run(main())
