# netizen

Simulasi reaksi netizen Indonesia terhadap sebuah post atau isu. Persona (emak-emak Bekasi, driver ojol, mahasiswa, buzzer, akun berita, dan lainnya) dinilai oleh [Jev](https://docs.typesafe.ai) dari TypeSafe: berhenti scroll atau tidak, aksi apa, dan bagaimana sikapnya. Hasilnya dibandingkan dengan komentar asli dari kasus nyata (Tapera, PPN 12%, UKT, MBG, dan lainnya).

Demo: https://moddestlab.com/netizen/

## Alur

1. **Retrieve**: cari kasus di `data/library` yang mirip dengan post baru, tampilkan mix komentar aslinya sebagai jangkar.
2. **Audience**: Jev menilai persona dan segmen minat mana yang ada di lingkaran pertama post itu.
3. **Simulate** (`spike/rounds.py`): ronde 1 netizen melihat post, ronde 2 pengikut melihat reaksi influencer. Dibaca dalam tiga skenario jangkauan: niche, ramai, viral.

## Menjalankan

Butuh `uv` dan `TYPESAFE_API_KEY` di `.env`. Semua dari folder ini.

```bash
uv run spike/run_issue.py --text "draf post kamu" --platforms X/Twitter,TikTok   # laporan di terminal
uv run spike/server.py                                                            # web di http://localhost:8798
uv run spike/backtest_youtube.py train                                            # uji terhadap komentar YouTube asli
```

`spike/personas.json`, `interest_segments.json`, `variants.json`, dan `influencers.json` adalah dunianya; `data/library/youtube_labels` adalah kasus nyata yang sudah dilabeli. Hasil run tersimpan di `spike/results/` (tidak di-commit).

## Status

Spike. Backtest 16 kasus YouTube: gap rata-rata mix sentimen sekitar 0.15 di kasus train dan test, lebih buruk pada kasus yang konteksnya tidak terbaca dari judul video saja.
