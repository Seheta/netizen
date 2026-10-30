# /// script
# requires-python = ">=3.11"
# dependencies = ["typesafe-sdk>=0.7.5"]
# ///
"""Backtest the new-issue workflow against the YouTube case library.

For each labeled case, the video with the most on-topic comments becomes the post (its title and
channel; we have no transcript). The workflow from run_issue.py runs on platform YouTube: audience
fit picks segments, one simulation, read under the three reach scenarios. The simulated posted
content is compared with the real per-comment stance mix of that video (and of the whole case).
gap = total variation distance between mixes (0 = identical, 1 = disjoint).

Run (from the netizen/ folder):
  uv run spike/backtest_youtube.py [train | test | case_id ...]
"""

import asyncio
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, Choice

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rounds import fmt_mix  # noqa: E402
from run_issue import (  # noqa: E402
    KEYS, LABELS, MAX_SEGMENTS, SCENARIOS, SEGMENT_MIN_FIT, audience_fit, scenario, segment_families, simulate,
)
from spike import COMMENT_KINDS, PRICE_PER_MTOK, comment_kinds, load_env, tone_of  # noqa: E402

ROOT = Path(__file__).resolve().parent
META = {c["id"]: c for c in json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))}
# Tune on train, report test untouched. Pairs of similar cases are split across the two sides.
SPLIT = {
    "train": ["c2_tapera", "c1_ppn12", "c6_mbg", "c10_boikot", "c9_timnas_saudi"],
    "test": ["c3_ukt", "c7_tunjangan_dpr", "c5_efisiensi", "c8_es_teh", "c4_pagar_laut"],
}


KINDS_DIR = LABELS.parent / "youtube_kinds"


async def label_kinds(client, case: dict, video: dict, messenger: str) -> tuple[dict[str, float], int]:
    """Label the video's on-topic comments with the same comment kinds the sim predicts (cached)."""
    out = KINDS_DIR / f"{case['id']}.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))["mix"], 0
    on = [c for c in video["comments"] if c["on_topic"] >= 0.5]
    counts, tokens = dict.fromkeys(COMMENT_KINDS, 0.0), 0
    for start in range(0, len(on), 40):
        chunk = on[start:start + 40]
        state = {"video_title": video["title"], "messenger": messenger,
                 "comments": {f"k{i:03d}": c["text"][:600] for i, c in enumerate(chunk)}}
        qs = {f"k{i:03d}": Choice(instructions=f"The subject is {case['subject']}; the speaker is `messenger`. What does "
                                               f"comment `comments.k{i:03d}` under this YouTube video mainly do?",
                                  criteria=comment_kinds(case["subject"])) for i in range(len(chunk))}
        r = await client.system_one(state=state, questions=qs)
        tokens += r.usage.input_tokens
        for i in range(len(chunk)):
            pr = r.answers[f"k{i:03d}"].probabilities
            counts[max(pr, key=pr.get)] += 1
    mix = {k: v / (len(on) or 1) for k, v in counts.items()}
    KINDS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"id": case["id"], "video": video["title"], "n": len(on), "mix": mix}, indent=1), encoding="utf-8")
    return mix, tokens


def real_mix(comments: list[dict]) -> dict[str, float]:
    on = [c for c in comments if c["on_topic"] >= 0.5]
    cnt = Counter(c["stance"] for c in on)
    return {k: cnt[k] / (len(on) or 1) for k in KEYS}


def gap(a: dict, b: dict) -> float:
    return sum(abs(a[k] - b[k]) for k in KEYS) / 2


async def run_case(client, case: dict, general: list[dict], fams: dict, influencers: list[dict], use_ctx: bool = True) -> dict:
    video = max(case["videos"], key=lambda v: sum(c["on_topic"] >= 0.5 for c in v["comments"]))
    text = f"Video YouTube berjudul \"{video['title']}\" dari channel {video['channel']}."
    if video.get("description"):
        text += f" Deskripsi: {video['description'][:400]}"
    ctx = META[case["id"]].get("context", "") if use_ctx else ""
    post = {"id": case["id"], "platform": "YouTube", "post": text, "subject": case["subject"],
            "messenger": META[case["id"]].get("messenger") or f"The YouTube channel {video['channel']}.",
            **({"context": ctx} if ctx else {})}
    members = [m for fam in fams.values() for m in fam]
    fit, t_fit = await audience_fit(client, text, "", general + members, post["messenger"], context=ctx)
    best = {sid: max(fit[m["id"]] for m in fam) for sid, fam in fams.items()}
    chosen_ids = sorted((s for s in fams if best[s] >= SEGMENT_MIN_FIT), key=lambda s: -best[s])[:MAX_SEGMENTS]
    personas = general + [m for sid in chosen_ids for m in fams[sid]]
    r1, posted, r2s, t_sim = await simulate(client, post, personas, influencers)
    res = {name: scenario(post, personas, influencers, fit, r1, posted, r2s, exp, pickup)
           for name, (exp, pickup) in SCENARIOS.items()}
    sims = {name: r["vocal"] for name, r in res.items()}
    real_kinds, t_kind = await label_kinds(client, case, video, post["messenger"])
    # Real kinds mapped to a stance mix through the same post position the sim used.
    mapped = tone_of({"x__comment": {"probabilities": real_kinds}, "post__position": r1["answers"]["post__position"]}, "x")
    real_kind_mix = dict.fromkeys(KEYS, 0.0)
    for lvl, pr in mapped["probabilities"].items():
        real_kind_mix[KEYS[0] if lvl <= 1 else KEYS[1] if lvl == 2 else KEYS[2]] += pr
    return {"id": case["id"], "video": video["title"], "segments": chosen_ids,
            "real_video": real_mix(video["comments"]),
            "real_case": real_mix([c for v in case["videos"] for c in v["comments"]]),
            "sim": sims, "sim_kinds": {n: r["kinds"] for n, r in res.items()}, "real_kinds": real_kinds,
            "real_kind_mix": real_kind_mix, "posted": [(i["id"], tk, pp) for i, tk, pp in posted],
            "raw": {"round1": r1, "round2": r2s}, "tokens": t_fit + t_sim + t_kind}


async def main() -> None:
    load_env()
    args = sys.argv[1:]
    use_ctx = "--no-context" not in args  # cases.json `context` = the public mood of the time
    args = [a for a in args if a != "--no-context"]
    only = set(SPLIT.get(args[0], args)) if args else set()
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(LABELS.glob("*.json"))
             if not only or p.stem in only]
    general = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    influencers = json.loads((ROOT / "influencers.json").read_text(encoding="utf-8"))
    fams = segment_families()
    async with AsyncTypeSafeClient() as client:
        sem = asyncio.Semaphore(4)

        async def guarded(c):
            async with sem:
                return await run_case(client, c, general, fams, influencers, use_ctx)
        res = await asyncio.gather(*(guarded(c) for c in cases))

    # Saved before the report: a print failure (e.g. emoji on a cp1252 console) must not lose paid results.
    out = ROOT / "results" / f"backtest_youtube_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    gaps = {name: [] for name in SCENARIOS}
    kgaps = {name: [] for name in SCENARIOS}
    short = lambda m: "  ".join(f"{k.split('_')[0][:3]}{'-' + k.split('_')[1][:2] if '_' in k else ''} {m.get(k, 0):.0%}"
                                for k in COMMENT_KINDS)
    for r in res:
        print(f"\n{r['id']}  | {r['video'][:70]}")
        print(f"  segments: {', '.join(s[2:] for s in r['segments']) or 'none'}")
        print(f"  {'real (old)':12} {fmt_mix(r['real_video'])}")
        print(f"  {'real (kinds)':12} {fmt_mix(r['real_kind_mix'])}")
        for name, m in r["sim"].items():
            g = gap(m, r["real_kind_mix"])
            gaps[name].append(g)
            print(f"  {'sim ' + name:12} {fmt_mix(m)}   gap {g:.3f}")
        print(f"  kinds real   {short(r['real_kinds'])}")
        for name, m in r["sim_kinds"].items():
            kg = sum(abs(m.get(k, 0) - r["real_kinds"].get(k, 0)) for k in COMMENT_KINDS) / 2
            kgaps[name].append(kg)
            if name == "niche":
                print(f"  kinds niche  {short(m)}   gap {kg:.3f}")
    print(f"\ncontext: {'on' if use_ctx else 'off'}")
    print("\nMean stance gap (real labeled by kinds): " + "  ".join(f"{n} {sum(g) / len(g):.3f}" for n, g in gaps.items()))
    print("Mean comment-kind gap:                   " + "  ".join(f"{n} {sum(g) / len(g):.3f}" for n, g in kgaps.items()))
    tokens = sum(r["tokens"] for r in res)
    print(f"Total input tokens {tokens:,} ≈ ${tokens * PRICE_PER_MTOK / 1e6:.4f} | raw: {out}")


if __name__ == "__main__":
    asyncio.run(main())
