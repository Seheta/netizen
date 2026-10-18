# /// script
# requires-python = ">=3.11"
# dependencies = ["typesafe-sdk>=0.7"]
# ///
"""Backtest the simulation against real Indonesian posts.

For each case, Jev labels the stance of real posts; the mix is compared with the
stance mix of what the simulated netizens would post on the same platform.
`sarcasm` measures Jev's accuracy on labeled sarcastic / non-sarcastic tweets.

Run (from the netizen/ folder):
  uv run spike/backtest.py tapera ppn_threads [sarcasm] [--sim spike/results/run_X.json]
"""

import argparse
import asyncio
import csv
import json
import random
from collections import Counter
from datetime import datetime
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, Noul, Score

from spike import PRICE_PER_MTOK, STANCE_LEVELS, bucket, load_env, vocal_stance_mix

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / "data"
BATCH = 50

CASES = {
    "tapera": {
        "files": ["tapera_train_tapera.csv", "tapera_val_tapera.csv", "tapera_test_tapera.csv"],
        "column": "text",
        "sample": 300,
        "context": "Real Indonesian tweets from May-June 2024 about Tapera.",
        "subject": "Tapera (the plan to deduct 3% of salaries for a public housing savings scheme)",
        "sim_post": "c2_tapera",
        "dataset_labels": {"2": "negative", "1": "neutral", "0": "positive"},  # inferred by reading the data
        "used_for_fitting": True,
    },
    "ppn_threads": {
        "files": ["threads_ppn12.csv"],
        "column": "text",
        "sample": None,
        "context": "Real Indonesian Threads posts from Nov 2024 - Jan 2025 about the VAT (PPN) increase to 12%.",
        "subject": "the increase of Indonesia's VAT (PPN) from 11% to 12%",
        "sim_post": "c1_ppn12_threads",
        "dataset_labels": None,
        "used_for_fitting": False,
    },
}


def read_csv(name: str) -> list[dict]:
    with open(DATA / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


async def ask_batches(client, items: list[str], make_question, context: str) -> tuple[list, int]:
    """Put up to BATCH texts in the state and ask one question per text."""
    async def one(start: int):
        chunk = items[start:start + BATCH]
        state = {"context": context, "posts": {f"t{i:03d}": t for i, t in enumerate(chunk)}}
        questions = {f"t{i:03d}": make_question(f"`posts.t{i:03d}`") for i in range(len(chunk))}
        r = await client.system_one(state=state, questions=questions)
        return [r.answers[f"t{i:03d}"] for i in range(len(chunk))], r.usage.input_tokens

    parts = await asyncio.gather(*(one(s) for s in range(0, len(items), BATCH)))
    return [a for answers, _ in parts for a in answers], sum(t for _, t in parts)


def stance_question(subject: str):
    def make(ref: str) -> Score:
        return Score(
            instructions=(
                f"How does the author of the Indonesian social media post {ref} feel about {subject}? "
                f"Read sarcasm, irony, and slang for what they really mean. Purely informational posts are neutral."
            ),
            criteria=STANCE_LEVELS,
        )
    return make


def sarcasm_question(ref: str) -> Noul:
    return Noul(
        instructions=(
            f"Is the Indonesian tweet {ref} sarcastic, meaning it says the opposite of, or mocks, what it "
            f"literally appears to say?"
        )
    )


def fmt(mix: dict[str, float]) -> str:
    return "  ".join(f"{k} {mix.get(k, 0):5.1%}" for k in ("negative", "neutral", "positive"))


def simulated_mix(sim_file: Path, post_id: str) -> dict[str, float]:
    personas = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    run = next((r for r in json.loads(sim_file.read_text(encoding="utf-8")) if r["post"]["id"] == post_id), None)
    if run is None:
        raise SystemExit(f"{sim_file.name} has no '{post_id}'. Run: uv run spike/spike.py {post_id}")
    return vocal_stance_mix(run["response"]["answers"], personas, run["post"]["platform"])


async def run_case(client, name: str, cfg: dict, sim_file: Path, rng: random.Random) -> tuple[int, dict]:
    rows = [r for f in cfg["files"] for r in read_csv(f) if r[cfg["column"]].strip()]
    if cfg["sample"] and len(rows) > cfg["sample"]:
        rows = rng.sample(rows, cfg["sample"])
    answers, tokens = await ask_batches(client, [r[cfg["column"]].strip() for r in rows],
                                        stance_question(cfg["subject"]), cfg["context"])
    jev = [bucket(max(a.probabilities, key=a.probabilities.get)) for a in answers]
    n = len(rows)
    real = {k: v / n for k, v in Counter(jev).items()}
    sim = simulated_mix(sim_file, cfg["sim_post"])
    gap = sum(abs(real.get(k, 0) - sim[k]) for k in sim) / 2

    tag = "used for fitting" if cfg["used_for_fitting"] else "HELD OUT, not used for fitting"
    print(f"\n=== {name} ({n} real posts, {tag}) ===")
    print(f"Real posts, labeled by Jev : {fmt(real)}")
    if cfg["dataset_labels"]:
        ds = [cfg["dataset_labels"][r["label"]] for r in rows]
        print(f"Real posts, dataset labels : {fmt({k: v / n for k, v in Counter(ds).items()})}")
    print(f"Simulation, posted content : {fmt(sim)}   [{sim_file.name}]")
    print(f"Gap (total variation)      : {gap:.3f}")
    print("Sample labels:")
    for r, j, a in list(zip(rows, jev, answers))[:10]:
        print(f"  {j:8} {a.score - 2:+.2f} | {r[cfg['column']].strip()[:110]!r}")
    detail = [{"text": r[cfg["column"]].strip(), "jev": j, "score": a.score - 2} for r, j, a in zip(rows, jev, answers)]
    return tokens, {"real": real, "sim": sim, "gap": gap, "posts": detail}


async def run_sarcasm(client, rng: random.Random) -> tuple[int, dict]:
    rows = rng.sample([r for r in read_csv("sarcastic_test.csv") if r["tweet"].strip()], 200)
    answers, tokens = await ask_batches(client, [r["tweet"].strip() for r in rows], sarcasm_question,
                                        "Real Indonesian tweets.")
    gold = [r["label"] == "1" for r in rows]
    probs = [a.noul for a in answers]
    print(f"\n=== sarcasm ({len(gold)} labeled tweets, {sum(gold)} sarcastic) ===")
    for thr in (0.3, 0.5, 0.7):
        pred = [p >= thr for p in probs]
        tp = sum(p and g for p, g in zip(pred, gold))
        fp = sum(p and not g for p, g in zip(pred, gold))
        fn = sum(g and not p for p, g in zip(pred, gold))
        acc = sum(p == g for p, g in zip(pred, gold)) / len(gold)
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        print(f"threshold {thr}: accuracy {acc:.0%}  precision {prec:.0%}  recall {rec:.0%}  F1 {f1:.2f}")
    print(f"(baseline 'always not sarcastic': {1 - sum(gold) / len(gold):.0%} accuracy)")
    return tokens, {"posts": [{"tweet": r["tweet"].strip(), "gold": g, "p": p} for r, g, p in zip(rows, gold, probs)]}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="+", choices=[*CASES, "sarcasm"])
    ap.add_argument("--sim", type=Path, help="simulation results file (default: latest run_*.json)")
    args = ap.parse_args()
    load_env()
    rng = random.Random(42)
    results_dir = ROOT / "results"
    sim_file = args.sim or max(results_dir.glob("run_*.json"))

    out, total = {}, 0
    async with AsyncTypeSafeClient() as client:
        for name in args.cases:
            if name == "sarcasm":
                tokens, out[name] = await run_sarcasm(client, rng)
            else:
                tokens, out[name] = await run_case(client, name, CASES[name], sim_file, rng)
            total += tokens

    print(f"\nInput tokens {total} ≈ ${total * PRICE_PER_MTOK / 1e6:.5f}")
    path = results_dir / f"backtest_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"raw: {path}")


if __name__ == "__main__":
    asyncio.run(main())
