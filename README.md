# netizen

Simulasi reaksi netizen Indonesia terhadap sebuah post atau isu. Persona (emak-emak Bekasi, driver ojol, mahasiswa, buzzer, akun berita, dan lainnya) dinilai oleh [Jev](https://docs.typesafe.ai) dari TypeSafe: berhenti scroll atau tidak, aksi apa, dan bagaimana sikapnya. Hasilnya dibandingkan dengan komentar asli dari kasus nyata (Tapera, PPN 12%, UKT, MBG, dan lainnya).

Demo: https://moddestlab.com/netizen/

## Alur

1. **Retrieve**: cari kasus di `data/library` yang mirip dengan post baru, tampilkan mix komentar aslinya sebagai jangkar.
2. **Audience**: Jev menilai persona dan segmen minat mana yang ada di lingkaran pertama post itu.
3. **Simulate** (`spike/rounds.py`): ronde 1 netizen melihat post, ronde 2 pengikut melihat reaksi influencer. Dibaca dalam tiga skenario jangkauan: niche, ramai, viral.

## Menjalankan

Butuh `uv`. Skrip CLI membaca `TYPESAFE_API_KEY` dari `.env`; halaman web memakai key yang diisi pengguna sendiri per request (tidak disimpan server). Semua dari folder ini.

```bash
uv run spike/run_issue.py --text "draf post kamu" --platforms X/Twitter,TikTok   # laporan di terminal
uv run spike/server.py                                                            # web di http://localhost:8798
uv run spike/backtest_youtube.py train                                            # uji terhadap komentar YouTube asli
```

Halaman web membuka dengan lima **contoh simulasi** (akun fiktif, isu nyata Agustus-Oktober 2026, hasil rekaman run asli di `web/samples/`, dibuat oleh `spike/record_samples.py`) yang bisa dilihat tanpa key. Sebuah post bisa diberi **konteks isu**: dua sampai empat kalimat tentang apa yang publik sudah tahu dan rasakan soal isu itu saat post muncul. Tanpa konteks, persona hanya menilai dari teks post dan pengetahuan umum; di backtest, konteks memotong gap kasus boikot dari 0.38 ke 0.22 dan Holywings dari 0.42 ke 0.11 (`uv run spike/backtest_youtube.py c10_boikot b2_holywings [--no-context]`, konteks ada di `spike/cases.json`). Post bisa berupa teks atau gambar (png/jpg, langsung dinilai Jev). Di web, sebuah post bisa dilanjutkan dengan **episode** berikutnya (klarifikasi, pembelaan, konten baru): persona diberi tahu post sebelumnya dan bagaimana reaksinya, dan timeline bisa mundur atau bercabang.

`spike/personas.json`, `interest_segments.json`, `variants.json`, dan `influencers.json` adalah dunianya; `data/library/youtube_labels` adalah kasus nyata yang sudah dilabeli. Hasil run tersimpan di `spike/results/` (tidak di-commit).

## Status

Spike. Backtest 16 kasus YouTube: gap rata-rata mix sentimen sekitar 0.15 di kasus train dan test, lebih buruk pada kasus yang konteksnya tidak terbaca dari judul video saja.
