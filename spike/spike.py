# /// script
# requires-python = ">=3.11"
# dependencies = ["typesafe-sdk>=0.7"]
# ///
"""Spike: can Jev judge how Indonesian netizen personas react to a post?

One request per post. The state holds the post plus all personas; each persona
gets three questions (stop scrolling, action, stance), plus two post-level ones.

Run:  uv run spike/spike.py            (from the netizen/ folder)
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

ROOT = Path(__file__).resolve().parent
PRICE_PER_MTOK = 0.042  # USD per million input tokens (jev, docs.typesafe.ai/models)


def load_env() -> None:
    env = ROOT.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


ACTIONS = {
    "ignore": "Scrolls past or reads silently without any visible reaction.",
    "like": "Only likes or reacts to it, without writing anything.",
    "comment_support": "Writes a comment that agrees with, praises, or defends the post or its subject.",
    "comment_negative": "Writes a comment that criticizes, complains about, mocks, or attacks the post or its subject.",
    "share_support": "Shares or reposts it because they like it or agree with it, recommending it to others.",
    "share_warn": "Forwards or reposts it to warn or inform family, friends, or community about bad news, without endorsing it.",
    "share_mock": "Shares or quote-posts it in order to criticize, roast, or make fun of it.",
    "create_post": "Makes their own new post, thread, or video about the topic (explainer, opinion piece, or reaction content).",
}

STANCE_LEVELS = [
    "Strongly against: angry, rejects or hates the subject of the post",
    "Somewhat against: disappointed, skeptical, or mildly annoyed by it",
    "Neutral or indifferent: has no real opinion or does not care",
    "Somewhat in favor: mildly positive, interested, or accepting",
    "Strongly in favor: enthusiastic, proud, or actively supportive",
]


# Persona fields that drive the simulation's arithmetic and are never shown to the model.
SIM_FIELDS = ("id", "weight", "presence", "post_volume", "parent", "share", "status")
VOCAL = ("comment_support", "comment_negative", "share_mock", "create_post")


def audience_weight(p: dict, platform: str) -> float:
    """Share of the platform's audience this persona stands for."""
    return p.get("weight", 1.0) * p.get("presence", {}).get(platform, 1.0)


def bucket(level: int) -> str:
    return "negative" if level <= 1 else "neutral" if level == 2 else "positive"


def vocal_stance_mix(answers: dict, personas: list[dict], platform: str) -> dict[str, float]:
    """Stance mix of the posts a scraper would see: who stops, posts publicly, and how often."""
    mix = dict.fromkeys(("negative", "neutral", "positive"), 0.0)
    for p in personas:
        pid = p["id"]
        posts = (audience_weight(p, platform) * p.get("post_volume", 1.0) * answers[f"{pid}__stop"]["noul"]
                 * sum(answers[f"{pid}__action"]["probabilities"].get(k, 0) for k in VOCAL))
        for level, prob in tone_of(answers, pid)["probabilities"].items():
            mix[bucket(int(level))] += posts * prob
    total = sum(mix.values()) or 1.0
    return {k: v / total for k, v in mix.items()}


GENERIC_SUBJECT = "the main subject of `post` (the policy, team, product, brand, or people it is about)"

# Comment kinds. Jev only makes forward judgments; the code maps praise/attack of the speaker to a
# stance through the post's own position (attacking someone who argues against a boycott is support
# for the boycott). Asking Jev for that inversion directly failed: it labels such comments neutral.
COMMENT_KIND_TEXT = {
    "support_issue": "Mainly says that {about} is good, right, deserved, or worth backing: in favor of it.",
    "oppose_issue": "Mainly says that {about} is bad, wrong, unfair, or a burden: against it.",
    "praise_speaker": "Mainly praises, thanks, defends, or prays for the speaker (the account or person behind the post).",
    "attack_speaker": "Mainly attacks, mocks, or criticizes the speaker (the account or person behind the post).",
    "neutral": "Asks a question, shares information, jokes about something else, or takes no clear side.",
}
COMMENT_KINDS = tuple(COMMENT_KIND_TEXT)


def comment_kinds(about: str) -> dict[str, str]:
    # The subject is written into each option: with a bare "supports the subject", Jev gave people
    # strongly against MPs' allowances a 30% chance of "supporting" it (it read: supporting the post).
    return {k: v.format(about=about) for k, v in COMMENT_KIND_TEXT.items()}


def persona_questions(pid: str, subject: str = "", has_messenger: bool = False) -> dict:
    p = f"`personas.{pid}`"
    about = subject or GENERIC_SUBJECT
    # The subject is written into each instruction: a reference to a `subject` state field weakened
    # stances (boycott +1.4 inline vs +0.3 by reference), and a messenger who argues one side pulled
    # personas toward that side unless the question says it is about their own view.
    return {
        f"{pid}__stop": Noul(
            instructions=(
                f"`post`{' by `messenger`' if has_messenger else ''} appears in the social media feed of the Indonesian "
                f"netizen described in {p}. Given their interests, platforms, and habits"
                f"{', and how they feel about that account or person (people mostly watch speakers they like or follow)' if has_messenger else ''}, "
                f"would this person stop scrolling and actually read or watch it?"
            )
        ),
        f"{pid}__action": Choice(
            instructions=(
                f"Assume the Indonesian netizen described in {p} has seen `post`. "
                f"Which visible action would this specific person most likely take, given how people like them "
                f"usually behave on `platform`?"
            ),
            criteria=ACTIONS,
        ),
        f"{pid}__stance": Score(
            instructions=(
                f"After seeing `post`, how does the Indonesian netizen described in {p} feel about {about}? "
                f"This is their own view of it, not whether they agree with `post`: if the post argues against it, "
                f"people who support it disagree with the post. Read sarcasm and irony for what they really mean."
            ),
            criteria=STANCE_LEVELS,
        ),
        f"{pid}__comment": comment_question(p, about, has_messenger),
    }


def comment_question(p: str, about: str, has_messenger: bool = False) -> Choice:
    # Stance and action are asked independently, so "comment_support" × "somewhat against" used to
    # count as a negative comment. Posted content takes its tone from this question instead.
    # Comments react to the speaker as much as to the issue (videos of a popular governor drew 90%+ praise).
    who = "`messenger`" if has_messenger else "the account that posted it and the people who appear in it"
    return Choice(
        instructions=(
            f"Suppose the Indonesian netizen described in {p} does write a public comment under `post`. The subject "
            f"is {about}; the speaker is {who}. How this person feels about the speaker matters as much as the issue. "
            f"What would their comment mainly do?"
        ),
        criteria=comment_kinds(about),
    )


def position_question(about: str) -> Score:
    return Score(instructions=f"What position does `post` itself, as its speaker presents it, take on {about}?",
                 criteria=STANCE_LEVELS)


# People who dislike a speaker rarely comment under the speaker's own post: in real YouTube comment
# sections 0–8% attack the speaker, while Jev predicts ~25%. Fitted on the train cases only.
ATTACK_POSTS = float(os.environ.get("NETIZEN_ATTACK_POSTS", "0.3"))


def kind_probs(kind: dict) -> dict:
    pr = dict(kind["probabilities"])
    pr["attack_speaker"] = pr.get("attack_speaker", 0) * ATTACK_POSTS
    return pr


def tone_of(answers: dict, pid: str, position: dict | None = None) -> dict:
    """Stance-level distribution of what this persona would post, from its comment kind and the post's
    position. Older results without a comment kind fall back to the tone score, then to the stance."""
    kind = answers.get(f"{pid}__comment")
    if not kind:
        return answers.get(f"{pid}__tone") or answers[f"{pid}__stance"]
    position = position or answers.get("post__position")
    pos = {int(k): v for k, v in position["probabilities"].items()} if position else {2: 1.0}
    out = dict.fromkeys(range(5), 0.0)
    pr = kind_probs(kind)
    out[4] += pr.get("support_issue", 0)
    out[0] += pr.get("oppose_issue", 0)
    out[2] += pr.get("neutral", 0)
    for lvl, q in pos.items():
        out[lvl] += pr.get("praise_speaker", 0) * q
        out[4 - lvl] += pr.get("attack_speaker", 0) * q
    return {"probabilities": out}


POST_QUESTIONS = {
    "post__sensitive": Noul(
        instructions=(
            "Does `post` touch a sensitive topic for Indonesian audiences (religion, ethnicity, social class, "
            "a profession being demeaned, or a burden on ordinary people) that could trigger public anger?"
        )
    ),
    "post__virality": Score(
        instructions="How widely would `post` likely spread on Indonesian social media within 48 hours?",
        criteria=[
            "Barely noticed: a few likes, no discussion",
            "Normal engagement for the account, no wider discussion",
            "Noticeably discussed in some communities",
            "Trending: discussed widely across many communities and platforms",
        ],
    ),
}


async def run_post(client: AsyncTypeSafeClient, post: dict, personas: list[dict]) -> dict:
    state = {
        "platform": post["platform"],
        "post": post["post"],
        "personas": {p["id"]: {k: v for k, v in p.items() if k not in SIM_FIELDS} for p in personas},
    }
    if post.get("subject"):
        state["subject"] = post["subject"]
    questions = dict(POST_QUESTIONS)
    for p in personas:
        questions.update(persona_questions(p["id"], post.get("subject", "")))
    result = await client.system_one(state=state, questions=questions)
    return {"post": post, "response": result.model_dump(mode="json")}


def stance_label(score: float) -> str:
    # score runs 0..4; map to -2..+2 for readability
    return f"{score - 2:+.2f}"


def report(run: dict, personas: list[dict]) -> tuple[str, int]:
    post, resp = run["post"], run["response"]
    a = resp["answers"]
    lines = [
        f"\n=== {post['id']} ({post['kind']}, {post['platform']}) ===",
        f"Post    : {post['post']}",
        f"Expected: {post['expected']}",
        f"Sensitive topic P={a['post__sensitive']['noul']:.2f} | "
        f"virality {a['post__virality']['score']:.2f}/3 (conf {a['post__virality']['confidence']:.2f})",
        "",
        f"{'persona':34} {'P(stop)':>7}  {'top action':18} {'p':>5}  {'stance(-2..+2)':>14}  {'conf':>4}",
    ]
    eq_num = eq_den = pop_num = pop_den = 0.0
    reach = {k: 0.0 for k in ACTIONS}
    for p in personas:
        pid = p["id"]
        stop = a[f"{pid}__stop"]["noul"]
        act = a[f"{pid}__action"]
        st = a[f"{pid}__stance"]
        top = max(act["probabilities"], key=act["probabilities"].get)
        lines.append(
            f"{p['label'][:34]:34} {stop:7.2f}  {top:18} {act['probabilities'][top]:5.2f}  "
            f"{stance_label(st['score']):>14}  {st['confidence']:4.2f}"
        )
        eq_num += (st["score"] - 2) * stop
        eq_den += stop
        w = audience_weight(p, post["platform"]) * stop
        pop_num += (st["score"] - 2) * w
        pop_den += w
        for k, v in act["probabilities"].items():
            reach[k] += w * v
    lines.append(
        f"\nNet sentiment [-2..+2], weighted by P(stop): equal personas {eq_num / eq_den:+.2f} | "
        f"{post['platform']} audience-weighted {pop_num / pop_den:+.2f}"
    )
    mix = "  ".join(f"{k} {v / pop_den:.0%}" for k, v in sorted(reach.items(), key=lambda kv: -kv[1]))
    lines.append(f"Audience that stops does: {mix}")
    vocal = vocal_stance_mix(a, personas, post["platform"])
    lines.append("Posted content (what a scraper would see): "
                 + "  ".join(f"{k} {v:.0%}" for k, v in vocal.items()))
    tokens = resp.get("usage", {}).get("input_tokens", 0)
    lines.append(f"Model {resp.get('model')} | input tokens {tokens}")
    return "\n".join(lines), tokens


async def main() -> None:
    load_env()
    if not os.environ.get("TYPESAFE_API_KEY"):
        sys.exit("TYPESAFE_API_KEY missing (put it in netizen/.env)")
    personas = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    posts = json.loads((ROOT / "posts.json").read_text(encoding="utf-8"))
    only = set(sys.argv[1:])
    if only:
        posts = [p for p in posts if p["id"] in only]

    async with AsyncTypeSafeClient() as client:
        runs = await asyncio.gather(*(run_post(client, p, personas) for p in posts))

    out = ROOT / "results" / f"run_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")

    total = 0
    for run in runs:
        text, tokens = report(run, personas)
        total += tokens
        print(text)
    print(f"\nTotal input tokens {total} ≈ ${total * PRICE_PER_MTOK / 1e6:.5f}  | raw results: {out}")


if __name__ == "__main__":
    asyncio.run(main())
