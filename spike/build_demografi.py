"""Build data/demografi/indonesia_2025.json from BPS / APJII figures and print the netizen composition.

Figures were collected by hand from BPS tables and from news/aggregators quoting BPS and APJII
(bps.go.id blocks automated access with HTTP 403). Each block records its source; 'secondary'
means the number came from a site citing BPS/APJII rather than the original table.

Run:  python spike/build_demografi.py      (from the netizen/ folder; no API calls)
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "demografi" / "indonesia_2025.json"

# Province: population 2025 (thousand) | % of population 5+ using internet, 2024: urban, rural, total
PROVINCES = [
    ("Aceh", 5626.0, 70.80, 58.66, 62.93),
    ("Sumatera Utara", 15785.8, 77.43, 69.69, 74.15),
    ("Sumatera Barat", 5914.3, 79.16, 69.78, 74.59),
    ("Riau", 6811.2, 84.30, 73.20, 77.68),
    ("Jambi", 3768.5, 78.17, 68.55, 71.76),
    ("Sumatera Selatan", 8928.5, 80.34, 64.50, 70.54),
    ("Bengkulu", 2138.0, 81.96, 65.01, 70.72),
    ("Lampung", 9522.9, 77.24, 71.37, 73.37),
    ("Kep. Bangka Belitung", 1550.8, 80.08, 70.41, 76.06),
    ("Kep. Riau", 2213.5, 91.52, 69.66, 89.26),
    ("DKI Jakarta", 10678.0, 87.84, None, 87.84),
    ("Jawa Barat", 50759.0, 79.42, 65.35, 76.62),
    ("Jawa Tengah", 38233.9, 76.08, 69.78, 73.15),
    ("DI Yogyakarta", 3781.5, 83.98, 68.24, 80.10),
    ("Jawa Timur", 42089.3, 75.22, 61.69, 69.36),
    ("Banten", 12537.4, 79.82, 56.77, 75.17),
    ("Bali", 4461.3, 81.73, 66.39, 77.56),
    ("Nusa Tenggara Barat", 5731.1, 72.88, 63.76, 68.52),
    ("Nusa Tenggara Timur", 5742.6, 76.88, 46.73, 54.84),
    ("Kalimantan Barat", 5766.0, 83.78, 64.02, 71.57),
    ("Kalimantan Tengah", 2845.0, 84.29, 68.19, 75.23),
    ("Kalimantan Selatan", 4323.3, 80.63, 68.96, 74.82),
    ("Kalimantan Timur", 4267.6, 87.33, 77.91, 84.44),
    ("Kalimantan Utara", 749.4, 81.92, 69.24, 77.44),
    ("Sulawesi Utara", 2721.4, 75.08, 60.13, 68.44),
    ("Sulawesi Tengah", 3156.1, 75.99, 55.70, 62.44),
    ("Sulawesi Selatan", 9563.1, 78.63, 62.43, 70.10),
    ("Sulawesi Tenggara", 2836.7, 78.79, 64.96, 70.36),
    ("Gorontalo", 1242.2, 74.03, 59.04, 65.92),
    ("Sulawesi Barat", 1525.3, 77.28, 63.90, 66.61),
    ("Maluku", 1970.6, 74.74, 48.44, 59.96),
    ("Maluku Utara", 1373.8, 80.10, 50.46, 59.17),
    ("Papua Barat", 587.6, 79.14, 55.75, 62.96),
    ("Papua Barat Daya", 636.4, 77.98, 53.40, 65.75),
    ("Papua", 1073.6, 77.56, 39.32, 62.24),
    ("Papua Selatan", 549.7, 74.09, 33.58, 48.44),
    ("Papua Tengah", 1492.3, 82.62, 12.30, 28.71),
    ("Papua Pegunungan", 1484.9, 41.86, 4.15, 6.76),
]
JAVA = {"DKI Jakarta", "Jawa Barat", "Jawa Tengah", "DI Yogyakarta", "Jawa Timur", "Banten"}

DATA = {
    "generation": {
        "year": 2025,
        "source": "BPS SUPAS 2025 (rilis 5 Mei 2026), via indonesiabaik.id & databoks (secondary)",
        "population_pct": {"post_gen_z": 19.65, "gen_z": 24.93, "millennial": 24.34, "gen_x": 19.70,
                           "boomer": 10.31, "pre_boomer": 1.07},
        "internet_penetration_pct": {
            "source": "APJII Survei Penetrasi Internet 2025 (WNI 13+, n=8.700, 10 Apr-16 Jul 2025), via Kontan (secondary)",
            "post_gen_z": 79.73, "gen_z": 87.80, "millennial": 89.12, "gen_x": 79.48, "boomer": 59.40, "pre_boomer": 20.88,
        },
    },
    "gender": {"source": "APJII 2025 via Kontan (secondary); sex ratio from BPS 2025",
               "internet_penetration_pct": {"male": 82.73, "female": 78.57}, "sex_ratio_2025": 101.9},
    "urban_rural_internet_users_pct": {"source": "APJII 2024 survey (share of users), via apjii.or.id",
                                       "urban": 69.5, "rural": 30.5},
    "economic_class": {
        "year": 2024,
        "source": "BPS kelas ekonomi 2024 (Susenas Maret 2024), via BPK & datasatu (secondary); kelas_atas = remainder",
        "definition": "per-capita spending as multiples of the poverty line (GK): rentan 1-1.5x, menuju menengah 1.5-3.5x, "
                      "menengah 3.5-17x, atas >17x",
        "population_pct": {"miskin": 9.03, "rentan_miskin": 24.23, "menuju_kelas_menengah": 49.22,
                           "kelas_menengah": 17.13, "kelas_atas": 0.39},
    },
    "education_15plus": {
        "source": "BPS Susenas, via Kompas data & databoks (secondary, years 2025-2026 mixed; verify)",
        "pct": {"tidak_punya_ijazah": 11.35, "sd": 23.90, "smp": 22.48, "sma_smk": 31.25, "perguruan_tinggi": 11.0},
    },
    "employment": {
        "year": "Agustus 2025",
        "source": "BPS BRS Keadaan Ketenagakerjaan, via Kemnaker Snapshot Statistik Ketenagakerjaan",
        "status_pct_of_workers": {"buruh_karyawan_pegawai": 38.74, "berusaha_sendiri": 21.40,
                                  "berusaha_dibantu_buruh_tidak_tetap": 13.86, "pekerja_bebas_nonpertanian": 5.16,
                                  "pekerja_bebas_pertanian": 4.42, "berusaha_dibantu_buruh_tetap": 3.46,
                                  "pekerja_keluarga_dan_lainnya": 12.96},
        "sector_pct_of_workers": {"pertanian": 28.15, "perdagangan": 18.73, "industri_pengolahan": 13.86,
                                  "akomodasi_makan_minum": 7.98, "konstruksi": 6.51, "jasa_pendidikan": 5.06,
                                  "jasa_lainnya": 4.46, "transportasi_pergudangan": 4.28, "administrasi_pemerintahan": 3.50,
                                  "jasa_perusahaan": 1.76, "jasa_kesehatan": 1.68, "lainnya": 4.06},
    },
    "religion": {"year": "Juni 2025", "source": "Dukcapil Kemendagri, via news (secondary); islam = remainder",
                 "pct": {"islam": 87.1, "kristen": 7.37, "katolik": 3.07, "hindu": 1.66, "buddha": 0.70, "lainnya": 0.1}},
    "platform_most_used": {
        "source": "APJII 2025 via selular.id (secondary). Share naming each platform as the one they use MOST, "
                  "not penetration: someone can use X daily without naming it.",
        "all": {"tiktok": 35.17, "youtube": 23.76, "facebook": 21.58, "instagram": 15.94, "x_twitter": 0.56},
        "gen_z": {"tiktok": 42.27, "instagram": 25.33, "youtube": 17.33, "facebook": 13.22},
        "millennial": {"tiktok": 33.40, "facebook": 27.03, "youtube": 23.86},
        "gen_x": {"youtube": 31.69, "tiktok": 28.58, "facebook": 27.19, "instagram": 7.15},
        "boomer": {"youtube": 39.11, "facebook": 22.0, "tiktok": 21.78, "instagram": 4.44},
    },
    "social_media_hours_per_day_pct": {"source": "APJII 2025 via GoodStats",
                                       "<1": 9.03, "1-2": 34.17, "2-3": 33.03, "3-4": 14.99, ">4": 8.78},
}


def main() -> None:
    rows = {name: {"population_k": pop, "internet_pct": {"urban": u, "rural": r, "total": t}}
            for name, pop, u, r, t in PROVINCES}
    total = sum(p["population_k"] for p in rows.values())
    assert len(rows) == 38 and abs(total - 284438.8) < 1, total
    data = {
        "_note": __doc__.strip().splitlines()[0],
        "province": {"year": 2025, "total_population_k": round(total, 1), "rows": rows,
                     "source": "BPS Penduduk menurut Provinsi 2025; internet: BPS Susenas 2024, % penduduk 5+ mengakses "
                               "internet 3 bulan terakhir menurut provinsi & klasifikasi daerah"},
        **DATA,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")

    gen = DATA["generation"]
    users = {k: gen["population_pct"][k] * gen["internet_penetration_pct"][k] / 100
             for k in ("gen_z", "millennial", "gen_x", "boomer", "pre_boomer")}  # APJII surveys 13+
    s = sum(users.values())
    print("\nNetizen 13+ by generation (population share × APJII penetration):")
    for k, v in users.items():
        print(f"  {k:11} {v / s:6.1%}   (population {gen['population_pct'][k]:5.2f}%)")

    by_prov = {n: p["population_k"] * p["internet_pct"]["total"] / 100 for n, p in rows.items()}
    su = sum(by_prov.values())
    print(f"\nInternet users by province (BPS 2024 rates): ≈ {su / 1000:.0f} juta (age 5+)")
    cum = 0.0
    for n, v in sorted(by_prov.items(), key=lambda kv: -kv[1])[:10]:
        cum += v / su
        print(f"  {n:22} {v / su:6.1%}   population {rows[n]['population_k'] / total:5.1%}   cumulative {cum:5.1%}")
    java_users = sum(v for n, v in by_prov.items() if n in JAVA) / su
    java_pop = sum(rows[n]["population_k"] for n in JAVA) / total
    print(f"  Jawa: {java_users:.1%} of netizens vs {java_pop:.1%} of population")


if __name__ == "__main__":
    main()
