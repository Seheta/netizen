# /// script
# requires-python = ">=3.11"
# dependencies = ["typesafe-sdk>=0.7.5"]
# ///
"""Rekam contoh simulasi untuk halaman web (tanpa key pengguna): lima akun fiktif, isu nyata.
Hasilnya JSON web_view di web/samples/<id>.json, dibaca halaman sebagai "contoh · rekaman".

Run (dari folder netizen):  uv run spike/record_samples.py [id ...]
Butuh TYPESAFE_API_KEY di .env. Sekitar 2 sen per sampel (dua platform).
"""

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_issue import run, save, web_view  # noqa: E402
from spike import load_env  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "web" / "samples"

# Akun fiktif, isu nyata. `follow` = episode kedua dari akun yang sama.
SAMPLES = [
    {"id": "kementerian", "kind": "pemerintah · defensif",
     "account": "Akun resmi sebuah kementerian", "messenger": "the official account of an Indonesian government ministry",
     "subject": "Tapera (the plan to deduct 3% of salaries for a public housing savings scheme)",
     "text": "Tapera bukan potongan baru. Ini tabungan Anda sendiri dan bisa dicairkan saat pensiun. Mohon pelajari dulu aturannya sebelum berkomentar. #TaperaUntukRakyat",
     "platforms": ["X/Twitter", "Instagram"],
     "follow": "Kami mendengar keberatan Anda. Skema Tapera akan dikaji ulang bersama serikat pekerja dan pengusaha, dan tidak ada potongan gaji sebelum aturan turunannya disepakati bersama."},
    {"id": "langkah", "kind": "brand · campaign baru",
     "account": "Langkah, sepatu lokal", "messenger": "Langkah, an Indonesian local sneaker brand from Bandung with a young middle-class following",
     "subject": "",
     "text": "Langkah resmi tampil di Paris Fashion Week 2026. Dari Bandung untuk dunia. Koleksi runway rilis 1 November, harga mulai Rp1,9 juta.",
     "platforms": ["Instagram", "TikTok"]},
    {"id": "kopisenja", "kind": "brand · isu nasional",
     "account": "Kopi Senja, jaringan kedai kopi", "messenger": "Kopi Senja, an Indonesian local coffee chain's official account",
     "subject": "the brand's refusal to take a side on the boycott of products linked to Israel",
     "text": "Kami tidak berpolitik. Kopi Senja hanya ingin jualan kopi yang enak untuk semua orang, apa pun pandangannya. Mohon jangan seret kami ke urusan boikot.",
     "platforms": ["X/Twitter", "TikTok"]},
    {"id": "raraglow", "kind": "influencer · di luar niche",
     "account": "@rara.glow, influencer skincare", "messenger": "@rara.glow, a skincare and beauty influencer with 300 thousand followers, mostly women aged 18 to 25",
     "subject": "the influencer's promotion of a paid trading class that promises 20% gains in three days",
     "text": "Jujur aku nyesel baru tahu sekarang. Ikut kelas trading 3 hari langsung cuan 20%. Link di bio, kuota terbatas ya bestie.",
     "platforms": ["Instagram", "TikTok"]},
    {"id": "karyawan", "kind": "akun biasa · berpotensi viral",
     "account": "Akun pribadi, pekerja kantoran", "messenger": "an ordinary personal account of an office worker with about 400 followers",
     "subject": "unpaid overtime demanded by an employer in the name of loyalty",
     "text": "Gaji UMR, disuruh lembur sampai jam 10 malam tanpa uang lembur. Pas protes, HRD bilang \"ini soal loyalitas\". Loyalitas kok cuma satu arah.",
     "platforms": ["X/Twitter", "Threads"]},
]


def reaction(view: dict, pl: str) -> str:
    """Ringkasan reaksi episode untuk `earlier`, sama dengan yang dibuat halaman web."""
    p = view["platforms"][pl]
    sc = p["scenarios"]["ramai"]
    v = sc["vocal"]
    infl = ", ".join(f"{i['label'].split(' (')[0]} ({i['take']})" for i in p["influencers"]) or "none"
    return (f"Of what netizens posted, {v['negative']:.0%} was against it, {v['neutral']:.0%} neutral, {v['positive']:.0%} in favor; "
            f"net sentiment {sc['net']:.2f} on a -2..+2 scale; {sc['reach']:.0%} stopped to read it; virality {p['virality']:.1f}/3. "
            f"Influencers who weighed in: {infl}.")


async def record(client, s: dict) -> dict:
    r = await run(client, s["text"], s["subject"], "", s["messenger"], s["platforms"], f"sample_{s['id']}")
    save(r, f"sample_{s['id']}")
    out = {"id": s["id"], "kind": s["kind"], "account": s["account"], "subject": s["subject"], "recorded": date.today().isoformat(),
           "episodes": [{"text": s["text"], "result": web_view(r)}]}
    if s.get("follow"):
        earlier = {pl: [{"text": s["text"], "reaction": reaction(out["episodes"][0]["result"], pl)}] for pl in s["platforms"]}
        r2 = await run(client, s["follow"], s["subject"], "", s["messenger"], s["platforms"], f"sample_{s['id']}_2", earlier=earlier)
        save(r2, f"sample_{s['id']}_2")
        out["episodes"].append({"text": s["follow"], "result": web_view(r2)})
    return out


async def main() -> None:
    load_env()
    only = set(sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    async with AsyncTypeSafeClient() as client:
        for s in SAMPLES:
            if only and s["id"] not in only:
                continue
            out = await record(client, s)
            (OUT / f"{s['id']}.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            for ep in out["episodes"]:
                for pl, p in ep["result"]["platforms"].items():
                    v = p["scenarios"]["ramai"]["vocal"]
                    print(f"{s['id']:12} {pl:10} neg {v['negative']:.0%} neu {v['neutral']:.0%} pos {v['positive']:.0%}  virality {p['virality']:.1f}  tokens {ep['result']['tokens']:,}")
    (OUT / "index.json").write_text(json.dumps([{k: s[k] for k in ("id", "kind", "account")} for s in SAMPLES], ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
