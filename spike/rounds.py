# /// script
# requires-python = ">=3.11"
# dependencies = ["typesafe-sdk>=0.7.5"]
# ///
"""Two-round simulation: netizens see a post, influencers react, followers see the influencer's take.

Round 1: one request per post. Netizen personas get stop/action/stance (as in spike.py);
         influencer archetypes get a take (do they post, and how) and a stance.
Round 2: one request per influencer that posts. The personas who follow that influencer
         see the original post plus the influencer's take, and Jev judges their stance and
         action again. Each persona's final stance mixes round 1 (not exposed) and round 2
         (exposed), weighted by how much of that segment follows each influencer.

--hire   "Which influencer should we hire": skip organic takes and instead make every
         influencer post a paid endorsement, one scenario each, ranked against no hire.

Run:  uv run spike/rounds.py [post_id ...] [--hire]     (from the netizen/ folder)
"""

import asyncio
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, Choice, Score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spike import (  # noqa: E402
    ACTIONS, POST_QUESTIONS, PRICE_PER_MTOK, SIM_FIELDS, STANCE_LEVELS, VOCAL, prefix,
    audience_weight, bucket, load_env, persona_questions, tone_of, kind_probs, comment_question, position_question, GENERIC_SUBJECT,
)

ROOT = Path(__file__).resolve().parent

TAKES = {
    "ignore": "Does not post anything about it.",
    "endorse": "Posts in support of it: praises, defends, or promotes it to their followers.",
    "criticize": "Posts to criticize, condemn, or call it out.",
    "explain": "Posts a calm explainer of what it means and who it affects, without taking a strong side.",
    "joke": "Turns it into a meme, parody, or joke for their followers.",
}
INFLUENCER_SIM_FIELDS = ("id", "followers")
MIN_FOLLOW = 0.05     # segments following less than this are not sent to round 2
MIN_POST_P = 0.25     # organic mode: influencers below this chance of posting are skipped

# Real posted-content mixes labeled by Jev in backtest.py, used to score held-out runs.
REAL_MIX = {
    "c1_ppn12_threads": {"negative": 0.756, "neutral": 0.209, "positive": 0.035},  # 86 Threads posts
    "c2_tapera": {"negative": 0.830, "neutral": 0.123, "positive": 0.047},         # 300 tweets (fit case)
}


def public(d: dict, hidden: tuple) -> dict:
    return {k: v for k, v in d.items() if k not in hidden}


def about(post: dict) -> str:
    return "`subject`" if post.get("subject") else \
        "the main subject of `post` (the policy, team, product, brand, or people it is about)"


def influencer_questions(iid: str, post: dict) -> dict:
    i = f"`influencers.{iid}`"
    ctx = prefix(bool(post.get("earlier")), bool(post.get("context")))
    return {
        f"{iid}__take": Choice(
            instructions=(
                f"{ctx}`post` is spreading on Indonesian social media. Would the Indonesian influencer described in {i} "
                f"post about it to their own followers, and if so with what kind of take? Unpaid, on their own initiative."
            ),
            criteria=TAKES,
        ),
        f"{iid}__stance": Score(
            instructions=f"{ctx}How does the influencer described in {i} personally feel about {about(post)}?",
            criteria=STANCE_LEVELS,
        ),
    }


# Asking for the stance from scratch in round 2 pulled every persona toward neutral with low
# confidence (Timnas win: all 13 shifted down even after endorsing takes). Asking for the shift
# from the round-1 stance anchors the judgment on the influencer's effect alone.
SHIFT_LEVELS = [
    "Pushed clearly more against it than before",
    "Pushed slightly more against it than before",
    "Unchanged: the influencer's take does not move their opinion",
    "Pulled slightly more in favor of it than before",
    "Pulled clearly more in favor of it than before",
]


def round2_questions(pid: str, post: dict) -> dict:
    p = f"`personas.{pid}`"
    ctx = prefix(bool(post.get("earlier")), bool(post.get("context")))
    return {
        f"{pid}__shift": Score(
            instructions=(
                f"{ctx}The Indonesian netizen described in {p} follows the influencer in `influencer`. After seeing `post` they "
                f"felt as in `personas.{pid}.stance_before`. Then they saw the influencer's take, described in "
                f"`influencer_take`. Given how much this person trusts, likes, or dislikes this kind of influencer, how does "
                f"the take change their feeling about {about(post)}, compared with before?"
            ),
            criteria=SHIFT_LEVELS,
        ),
        f"{pid}__action": Choice(
            instructions=(
                f"After seeing `post` and the influencer's take in `influencer_take`, which visible action would the "
                f"netizen described in {p} most likely take about the original post or its subject, given how people like "
                f"them usually behave on `platform`?"
            ),
            criteria=ACTIONS,
        ),
        f"{pid}__comment": comment_question(p, about(post), bool(post.get("messenger")), bool(post.get("earlier")), bool(post.get("context"))),
    }


def take_text(inf: dict, take: str, attitude: int, paid: bool) -> str:
    who = f"{inf['label']} ({inf['followers_total']} followers)"
    if paid:
        head = f"{who} was paid by the brand to post about it; the post is marked as a paid promotion (#ad)."
    else:
        head = f"{who} posted about it on their own initiative."
    return f"{head} Their take: {TAKES[take]} Their attitude: {STANCE_LEVELS[attitude]}."


async def ask(client: AsyncTypeSafeClient, state: dict, questions: dict) -> dict:
    result = await client.system_one(state=state, questions=questions)
    return result.model_dump(mode="json")


# Big requests blur Jev's answers: in a 24-persona round 1, devout personas came out slightly against
# the Palestine boycott, while the same personas asked in a small request were strongly for it.
# Personas are therefore asked in small chunks, and influencers in their own request.
CHUNK = int(os.environ.get("NETIZEN_CHUNK", "4"))


def merge(responses: list[dict]) -> dict:
    out = {"answers": {}, "usage": {"input_tokens": 0}}
    for r in responses:
        out["answers"].update(r["answers"])
        out["usage"]["input_tokens"] += r.get("usage", {}).get("input_tokens", 0)
        out.setdefault("model", r.get("model"))
    return out


async def round1(client, post: dict, personas: list[dict], influencers: list[dict]) -> dict:
    base = {"platform": post["platform"], "post": post["post"]}
    for k in ("messenger", "earlier", "context"):
        if post.get(k):
            base[k] = post[k]
    flags = (post.get("subject", ""), bool(post.get("messenger")), bool(post.get("earlier")), bool(post.get("context")))
    jobs = [ask(client, {**base, "influencers": {i["id"]: public(i, INFLUENCER_SIM_FIELDS) for i in influencers}},
                {**POST_QUESTIONS, "post__position": position_question(about(post)), **{k: v for i in influencers for k, v in influencer_questions(i["id"], post).items()}})]
    for start in range(0, len(personas), CHUNK):
        chunk = personas[start:start + CHUNK]
        qs = {k: v for p in chunk for k, v in persona_questions(p["id"], *flags).items()}
        jobs.append(ask(client, {**base, "personas": {p["id"]: public(p, SIM_FIELDS) for p in chunk}}, qs))
    return merge(await asyncio.gather(*jobs))


async def round2(client, post: dict, personas: list[dict], inf: dict, take: str, r1: dict) -> dict:
    followers = [p for p in personas if inf["followers"].get(p["id"], 0) >= MIN_FOLLOW]
    a1 = r1["answers"]
    base = {"platform": post["platform"], "post": post["post"], "influencer": public(inf, INFLUENCER_SIM_FIELDS),
            "influencer_take": take}
    for k in ("messenger", "earlier", "context"):
        if post.get(k):
            base[k] = post[k]
    jobs = []
    for start in range(0, len(followers), CHUNK):
        chunk = followers[start:start + CHUNK]
        state = {**base, "personas": {p["id"]: dict(public(p, SIM_FIELDS),
                                                    stance_before=STANCE_LEVELS[round(a1[f"{p['id']}__stance"]["score"])])
                                      for p in chunk}}
        jobs.append(ask(client, state, {k: v for p in chunk for k, v in round2_questions(p["id"], post).items()}))
    return merge(await asyncio.gather(*jobs))


# ---------------------------------------------------------------- aggregation (no API calls)

def dist(answer: dict) -> dict[int, float]:
    return {int(k): v for k, v in answer["probabilities"].items()}


def net(d: dict[int, float]) -> float:
    return sum((lvl - 2) * pr for lvl, pr in d.items())


def shifted(stance: dict[int, float], shift: dict[int, float]) -> dict[int, float]:
    """Move each stance level by the shift (level - 2), clipped to the 0..4 scale."""
    out = dict.fromkeys(range(5), 0.0)
    for lvl, p in stance.items():
        for s, q in shift.items():
            out[min(4, max(0, lvl + s - 2))] += p * q
    return out


def mix(parts: list[tuple[float, dict]]) -> dict:
    out: dict = {}
    for w, d in parts:
        for k, v in d.items():
            out[k] = out.get(k, 0.0) + w * v
    return out


def combine(post: dict, personas: list[dict], influencers: list[dict], r1: dict,
            exposures: list[tuple[dict, float, dict]], aud_weights: dict[str, float] | None = None) -> dict:
    """exposures: (influencer, P(influencer posts), round-2 answers). Returns per-persona and population results.
    aud_weights overrides each persona's share of the audience (reach scenarios in run_issue.py)."""
    a1 = r1["answers"]
    rows, pop = [], {"w": 0.0, "net1": 0.0, "net2": 0.0, "reach1": 0.0, "reach2": 0.0, "aud": 0.0, "pro": 0.0, "contra": 0.0}
    vocal = dict.fromkeys(("negative", "neutral", "positive"), 0.0)
    kinds: dict[str, float] = {}
    for p in personas:
        pid = p["id"]
        stop1 = a1[f"{pid}__stop"]["noul"]
        s1, act1 = dist(a1[f"{pid}__stance"]), a1[f"{pid}__action"]["probabilities"]
        exp = []
        for inf, p_post, a2 in exposures:
            e = inf["followers"].get(pid, 0) * p_post
            if e > 0 and f"{pid}__shift" in a2:
                exp.append((e, shifted(s1, dist(a2[f"{pid}__shift"])), a2[f"{pid}__action"]["probabilities"],
                            dist(tone_of(a2, pid, a1.get("post__position"))),
                            kind_probs(a2[f"{pid}__comment"]) if f"{pid}__comment" in a2 else {}))
        unexposed = math.prod(1 - e for e, *_ in exp)
        e_sum = sum(e for e, *_ in exp)
        if exp:
            s2_exp = mix([(e / e_sum, s) for e, s, *_ in exp])
            act_exp = mix([(e / e_sum, a) for e, _, a, *_ in exp])
            tone_exp = mix([(e / e_sum, t) for e, _, _, t, _ in exp])
            kind_exp = mix([(e / e_sum, k) for *_, k in exp])
            s2 = mix([(unexposed, s1), (1 - unexposed, s2_exp)])
        else:
            s2_exp, act_exp, tone_exp, kind_exp, s2 = None, None, None, None, s1
        # Reading the issue at all: stopped for the original, or saw it via an influencer they follow.
        reach2 = 1 - (1 - stop1) * unexposed
        aud = aud_weights[pid] if aud_weights is not None else audience_weight(p, post["platform"])
        pop["aud"] += aud
        pop["reach1"] += aud * stop1
        pop["reach2"] += aud * reach2
        pop["net1"] += aud * stop1 * net(s1)
        pop["net2"] += aud * reach2 * net(s2)
        pop["w"] += aud * reach2
        pop["pro"] += aud * reach2 * (s2.get(3, 0) + s2.get(4, 0))
        pop["contra"] += aud * reach2 * (s2.get(0, 0) + s2.get(1, 0))
        # Posted content: original readers act as in round 1, influencer-exposed readers as in round 2.
        # Its tone is the tone of the comment they would write, not their private stance.
        vol = aud * p.get("post_volume", 1.0)
        parts = [(stop1 * unexposed, dist(tone_of(a1, pid)), act1, kind_probs(a1[f"{pid}__comment"]) if f"{pid}__comment" in a1 else {})]
        if exp:
            parts.append((1 - unexposed, tone_exp, act_exp, kind_exp))
        for w, s, act, kd in parts:
            loud = vol * w * sum(act.get(k, 0) for k in VOCAL)
            for lvl, pr in s.items():
                vocal[bucket(lvl)] += loud * pr
            for k, pr in kd.items():
                kinds[k] = kinds.get(k, 0.0) + loud * pr
        rows.append({"id": pid, "label": p["label"], "stop1": stop1, "exposed": 1 - unexposed,
                     "net1": net(s1), "net2": net(s2), "readers": aud * reach2})
    reach1_w = pop["reach1"] or 1.0
    total_vocal = sum(vocal.values()) or 1.0
    return {
        "rows": rows,
        "reach1": pop["reach1"] / pop["aud"],
        "reach2": pop["reach2"] / pop["aud"],
        "net1": pop["net1"] / reach1_w,
        "net2": pop["net2"] / (pop["w"] or 1.0),
        "pro": pop["pro"] / pop["aud"],         # share of the whole platform audience now in favor
        "contra": pop["contra"] / pop["aud"],   # ... and now against
        "vocal": {k: v / total_vocal for k, v in vocal.items()},
        "kinds": {k: v / (sum(kinds.values()) or 1.0) for k, v in kinds.items()},
    }


def tokens_of(*responses: dict) -> int:
    return sum(r.get("usage", {}).get("input_tokens", 0) for r in responses)


# ---------------------------------------------------------------- reports

def influencer_table(r1: dict, influencers: list[dict]) -> list[str]:
    a = r1["answers"]
    lines = [f"{'influencer':40} {'P(post)':>7}  {'top take':10} {'p':>5}  {'stance':>6}"]
    for inf in influencers:
        tp = a[f"{inf['id']}__take"]["probabilities"]
        top = max((k for k in tp if k != "ignore"), key=tp.get)
        lines.append(f"{inf['label'][:40]:40} {1 - tp.get('ignore', 0):7.2f}  {top:10} {tp[top]:5.2f}  "
                     f"{a[inf['id'] + '__stance']['score'] - 2:+6.2f}")
    return lines


def fmt_mix(m: dict) -> str:
    return "  ".join(f"{k} {v:.0%}" for k, v in m.items())


def report_organic(post: dict, influencers: list[dict], r1: dict, posted: list, res: dict) -> str:
    a = r1["answers"]
    lines = [
        f"\n=== {post['id']} ({post['platform']}) — organic ===",
        f"Post    : {post['post']}",
        f"Expected: {post['expected']}",
        f"Virality {a['post__virality']['score']:.2f}/3 | sensitive P={a['post__sensitive']['noul']:.2f}",
        "", "Round 1 — influencer takes:", *influencer_table(r1, influencers),
        "", "Round 2 — posting influencers: "
        + (", ".join(f"{inf['label']} [{take}, P={pp:.2f}]" for inf, take, pp in posted) or "none"),
        "", f"{'persona':38} {'P(stop)':>7} {'exposed':>8} {'net r1':>7} {'net r2':>7} {'shift':>6}",
    ]
    for r in res["rows"]:
        lines.append(f"{r['label'][:38]:38} {r['stop1']:7.2f} {r['exposed']:8.2f} {r['net1']:+7.2f} "
                     f"{r['net2']:+7.2f} {r['net2'] - r['net1']:+6.2f}")
    lines += [
        "",
        f"Reach (share of {post['platform']} audience reading the issue): r1 {res['reach1']:.0%} -> r2 {res['reach2']:.0%}",
        f"Net sentiment [-2..+2] among readers: r1 {res['net1']:+.2f} -> r2 {res['net2']:+.2f}",
        f"Posted content after r2: {fmt_mix(res['vocal'])}",
    ]
    if post["id"] in REAL_MIX:
        real = REAL_MIX[post["id"]]
        gap = sum(abs(real[k] - res["vocal"][k]) for k in real) / 2
        lines.append(f"Real posted content    : {fmt_mix(real)}  -> gap {gap:.3f}")
    return "\n".join(lines)


def report_hire(post: dict, base: dict, scenarios: list[tuple[dict, dict]]) -> str:
    lines = [
        f"\n=== {post['id']} ({post['platform']}) — which influencer to hire (paid endorsement) ===",
        f"Post: {post['post']}",
        "",
        f"{'scenario':40} {'reach':>6} {'pro':>5} {'contra':>6} {'Δpro':>6} {'Δcontra':>8} {'net':>6}  posted content",
    ]
    rows = [("(no hire)", base)] + [(inf["label"], res) for inf, res in scenarios]
    for label, res in sorted(rows, key=lambda r: -(r[1]["pro"] - r[1]["contra"])):
        lines.append(f"{label[:40]:40} {res['reach2']:6.0%} {res['pro']:5.0%} {res['contra']:6.0%} "
                     f"{res['pro'] - base['pro']:+6.0%} {res['contra'] - base['contra']:+8.0%} {res['net2']:+6.2f}  "
                     f"{fmt_mix(res['vocal'])}")
    lines.append("\npro/contra = share of the whole platform audience that read it and is in favor / against; "
                 "sorted by pro − contra. net = mean stance of readers only.")
    return "\n".join(lines)


# ---------------------------------------------------------------- main

async def run_post(client, post, personas, influencers, hire: bool) -> tuple[str, dict, int]:
    r1 = await round1(client, post, personas, influencers)
    a = r1["answers"]
    if hire:
        base = combine(post, personas, influencers, r1, [])
        r2s = await asyncio.gather(*(
            round2(client, post, personas, inf, take_text(inf, "endorse", 4, paid=True), r1) for inf in influencers))
        scenarios = [(inf, combine(post, personas, influencers, r1, [(inf, 1.0, r2["answers"])]))
                     for inf, r2 in zip(influencers, r2s)]
        raw = {"post": post, "round1": r1, "round2": {i["id"]: r for i, r in zip(influencers, r2s)}}
        return report_hire(post, base, scenarios), raw, tokens_of(r1, *r2s)

    posted = []
    for inf in influencers:
        tp = a[f"{inf['id']}__take"]["probabilities"]
        p_post = 1 - tp.get("ignore", 0)
        if p_post >= MIN_POST_P:
            take = max((k for k in tp if k != "ignore"), key=tp.get)
            posted.append((inf, take, p_post))
    r2s = await asyncio.gather(*(
        round2(client, post, personas, inf,
               take_text(inf, take, max(dist(a[f"{inf['id']}__stance"]).items(), key=lambda kv: kv[1])[0], paid=False), r1)
        for inf, take, _ in posted))
    res = combine(post, personas, influencers, r1, [(inf, pp, r2["answers"]) for (inf, _, pp), r2 in zip(posted, r2s)])
    raw = {"post": post, "round1": r1, "round2": {inf["id"]: r for (inf, _, _), r in zip(posted, r2s)}}
    return report_organic(post, influencers, r1, posted, res), raw, tokens_of(r1, *r2s)


async def main() -> None:
    load_env()
    if not os.environ.get("TYPESAFE_API_KEY"):
        sys.exit("TYPESAFE_API_KEY missing (put it in netizen/.env)")
    args = sys.argv[1:]
    hire = "--hire" in args
    only = {a for a in args if not a.startswith("--")}
    personas = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    influencers = json.loads((ROOT / "influencers.json").read_text(encoding="utf-8"))
    posts = json.loads((ROOT / "posts.json").read_text(encoding="utf-8"))
    if only:
        posts = [p for p in posts if p["id"] in only]

    async with AsyncTypeSafeClient() as client:
        runs = await asyncio.gather(*(run_post(client, p, personas, influencers, hire) for p in posts))

    out = ROOT / "results" / f"rounds{'_hire' if hire else ''}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps([raw for _, raw, _ in runs], ensure_ascii=False, indent=2), encoding="utf-8")
    total = 0
    for text, _, tokens in runs:
        print(text)
        total += tokens
    print(f"\nTotal input tokens {total} ≈ ${total * PRICE_PER_MTOK / 1e6:.5f}  | raw results: {out}")


if __name__ == "__main__":
    asyncio.run(main())
