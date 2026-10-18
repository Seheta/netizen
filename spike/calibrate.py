"""Fit the posting volume of chosen personas so the simulated posted-content mix
matches a real mix. Uses a saved simulation run; makes no API calls.

Run:  uv run --no-project --with typesafe-sdk python spike/calibrate.py
"""

import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spike import vocal_stance_mix  # noqa: E402

ROOT = Path(__file__).resolve().parent
POST_ID = "c2_tapera"
# Real Tapera tweets labeled by Jev in backtest.py (300 tweets, May-June 2024).
TARGET = {"negative": 0.853, "neutral": 0.090, "positive": 0.057}
FIT = ("p10_buzzer", "p11_media")
GRID = (0.25, 0.5, 1, 1.5, 2, 3, 4, 5, 6, 8)


def distance(mix: dict) -> float:
    return sum(abs(mix[k] - TARGET[k]) for k in TARGET) / 2  # total variation distance


def main() -> None:
    personas = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
    sim_file = max((ROOT / "results").glob("run_*.json"))
    run = next(r for r in json.loads(sim_file.read_text(encoding="utf-8")) if r["post"]["id"] == POST_ID)
    answers, platform = run["response"]["answers"], run["post"]["platform"]
    by_id = {p["id"]: p for p in personas}

    current = vocal_stance_mix(answers, personas, platform)
    print(f"run {sim_file.name}, post {POST_ID}")
    print(f"target : {TARGET}")
    print(f"current: { {k: round(v, 3) for k, v in current.items()} }  distance {distance(current):.3f}  "
          f"({', '.join(f'{pid}={by_id[pid]["post_volume"]}' for pid in FIT)})")

    results = []
    for vols in itertools.product(GRID, repeat=len(FIT)):
        trial = [dict(p, post_volume=vols[FIT.index(p["id"])]) if p["id"] in FIT else p for p in personas]
        mix = vocal_stance_mix(answers, trial, platform)
        results.append((distance(mix), vols, mix))
    results.sort(key=lambda r: r[0])
    print("\nbest fits:")
    for d, vols, mix in results[:5]:
        print(f"  {dict(zip(FIT, vols))}  ->  " + "  ".join(f"{k} {v:.1%}" for k, v in mix.items())
              + f"  distance {d:.3f}")


if __name__ == "__main__":
    main()
