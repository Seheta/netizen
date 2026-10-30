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

KARHUTLA = ('Forest and peat fires (karhutla) have burned since July 2026 (about 95,000 hectares in July alone); Kalimantan and '
            'Sumatra have breathed toxic haze for four months, worst on 13-15 October, with schools closed and ojol and street '
            'vendors losing income. Malaysia and Singapore protested the cross-border haze, a class action is being prepared, '
            'and NGOs, clerics and regional leaders demand national-disaster status, which the government has not granted. '
            "President Prabowo said he hoped for rain, which netizens mocked ('then what is the government for?'); a governor "
            'went viral having a lavish breakfast abroad during the haze, and influencers complained Instagram throttled their '
            'karhutla posts. The dominant narrative: the government lets corporate land burn and understates the crisis.')

# Akun fiktif, isu nyata (Agustus-Oktober 2026); `context` = suasana publik saat itu. `follow` = episode kedua dari akun yang sama.
SAMPLES = [
    {"id": "karhutla", "kind": "pemerintah · defensif",
     "account": "Akun resmi sebuah kementerian", "messenger": "the official account of an Indonesian government ministry",
     "subject": "the government's handling of the 2026 forest and peat fires (karhutla) and the haze",
     "context": KARHUTLA,
     "text": "Titik api turun 60% dalam sepekan. Satgas bekerja 24 jam, sisa 639 hektare sedang ditangani. Kabut asap lintas batas bukan hanya dari Indonesia. Mohon tidak menyebarkan foto lama dan hoaks. #SiagaKarhutla",
     "platforms": ["X/Twitter", "Instagram"],
     "follow": "Kami minta maaf kepada warga yang empat bulan menghirup asap. Status bencana nasional sedang dikaji bersama BNPB. Masker, oksigen, dan sekolah daring diperluas, dan data titik api harian kami buka untuk publik mulai hari ini."},
    {"id": "langkah", "kind": "brand · campaign baru",
     "account": "Langkah, sepatu lokal", "messenger": "Langkah, an Indonesian local sneaker brand from Bandung with a young middle-class following",
     "subject": "",
     "context": "Indonesia won the inaugural FIFA ASEAN Cup on 5 October 2026, beating Thailand on penalties at Gelora Bung Karno; the euphoria is huge. But grooming brand Kahf's 'Hati-Hati Beda Level' meme, with the Indonesian flag above its neighbours, triggered boycott calls in Malaysia against Indonesian brands and a public apology, so chest-beating marketing is under scrutiny. Netizens of Indonesia and Malaysia are still trading insults on Threads.",
     "text": "Langkah x Timnas: edisi JUARA ASEAN. 2.026 pasang, bernomor, merah-putih di sol. Rilis Jumat 10.00 WIB, Rp1,2 juta. Untuk yang percaya sejak babak grup.",
     "platforms": ["Instagram", "TikTok"]},
    {"id": "kopisenja", "kind": "brand · isu nasional",
     "account": "Kopi Senja, jaringan kedai kopi", "messenger": "Kopi Senja, an Indonesian local coffee chain's official account",
     "subject": "the Indonesia Sadar student protests against the government's two-year record",
     "context": "On 28 October 2026 (Youth Pledge Day) BEM UI and the Komite Sadar alliance held the 'Indonesia Sadar' protest at Bundaran HI, marking two years of the Prabowo-Gibran government with five demands (cheaper education, karhutla, democracy, the economy) under the slogan 'Tepati atau Pergi'. Clashes with police left students fainting; pro-government accounts call the protesters NGO puppets, while much of the public sympathises. Brands have so far stayed silent.",
     "text": "Gerai Kopi Senja Sarinah dan Thamrin buka sampai tengah malam untuk siapa pun yang butuh duduk, air putih, dan colokan. Mahasiswa, wartawan, petugas. Kami tidak berpihak pada partai; kami berpihak pada orang yang berdiri di jalan untuk negerinya. #IndonesiaSadar",
     "platforms": ["X/Twitter", "TikTok"]},
    {"id": "raraglow", "kind": "influencer · di luar niche",
     "account": "@rara.glow, influencer skincare", "messenger": "@rara.glow, a skincare and beauty influencer with 300 thousand followers, mostly women aged 18 to 25",
     "subject": "the influencer's dismissal of the karhutla haze as normal",
     "context": KARHUTLA + " Netizens have just punished influencers seen as tone-deaf: Vilmei's 'Day 1 Cari Kerja' job-hunt parody and Irenna Kristyn's mockery of cost-of-living protests both drew mass criticism and forced apologies in October.",
     "text": "Guys, asap di Kalimantan itu tiap tahun ada, jangan lebay dong. Yang penting kulit tetap aman: double cleanse, SPF 50, dan serum antioksidan. Link produk di bio, diskon sampai Minggu.",
     "platforms": ["Instagram", "TikTok"]},
    {"id": "asn", "kind": "akun biasa · berpotensi viral",
     "account": "Akun pribadi, pegawai negeri", "messenger": "an ordinary personal account of a junior civil servant with about 500 followers",
     "subject": "government offices ordering staff to post the #2TahunGerakNyata campaign from personal accounts",
     "context": "A letter from the presidential communications office (Bakom RI, 12 October 2026) and a follow-up from the Ministry of Immigration and Corrections (13 October) leaked, instructing all units to post about the government's two-year achievements on 13-20 October with mandatory phrases ('2 Tahun Gerak Nyata', 'Transformasi Bangsa') and the hashtag #2TahunGerakNyata. Netizens call it 'buzzer berseragam' (uniformed buzzers), especially while prison scandals remain unresolved; the government says it is normal public communication.",
     "text": "Saya PNS golongan III. Hari ini kami diwajibkan posting #2TahunGerakNyata dari akun pribadi, lengkap dengan kalimat yang sudah ditentukan. Ini akun saya, bukan akun kantor. Saya posting ini saja.",
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
    r = await run(client, s["text"], s["subject"], "", s["messenger"], s["platforms"], f"sample_{s['id']}", context=s.get("context", ""))
    save(r, f"sample_{s['id']}")
    out = {"id": s["id"], "kind": s["kind"], "account": s["account"], "subject": s["subject"], "recorded": date.today().isoformat(),
           "episodes": [{"text": s["text"], "result": web_view(r)}]}
    if s.get("follow"):
        earlier = {pl: [{"text": s["text"], "reaction": reaction(out["episodes"][0]["result"], pl)}] for pl in s["platforms"]}
        r2 = await run(client, s["follow"], s["subject"], "", s["messenger"], s["platforms"], f"sample_{s['id']}_2", earlier=earlier, context=s.get("context", ""))
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
