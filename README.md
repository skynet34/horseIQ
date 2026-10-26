# HorseIQ

TJK yarış programlarındaki atları geçmiş performanslarına göre **birbirini etkileyerek** sanal olarak koşturan web uygulaması.

**Yarışı seç → Koştur → Sonucu gör → İstersen müdahale et → Yeniden koştur.**

> Durum ve ilerleme raporu: [docs/RAPOR.md](docs/RAPOR.md) · Veri erişimi: [docs/DATA_ACCESS.md](docs/DATA_ACCESS.md) · Mimari: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

⚠️ **Gerçek veri yalnızca elle indirilen dosyalardan gelir** (26 Ekim 2026: 01.10.2026 Kocaeli günü + 1. koşunun Accurace raporları denendi). tjk.org ve accurace.net otomatik erişime (robots.txt) izin vermiyor; HorseIQ'nun TJK veri servisi anahtarı (authKey) ve Accurace lisansı yok. Uygulama gerçek veri içe aktarıldığında onunla çalışır; o zamana kadar yalnızca açıkça işaretlenmiş **DEMO** (sentetik) dünya ile denenebilir. Gerçek ve demo veri hiçbir zaman karışmaz.

## Yapı

```
backend/           Python 3.12+ · FastAPI · SQLAlchemy (SQLite yerel, PostgreSQL/Supabase üretim)
  horseiq/
    collectors/    tjk/ (authKey API adaptörü + elle kaydedilen sayfa ayrıştırıcı), accurace/ (hazır, pasif), demo.py, importer.py
    form/          geçmiş koşu seçimi (Mod A gün / Mod B yarış sayısı), hız normalizasyonu, form puanı, simülasyon profili
    sim/           zaman adımlı yarış motoru (enerji, liderlik mücadelesi, trafik, müdahaleler), Monte Carlo
    backtest/      kronolojik, sızıntısız geriye dönük test
    api/           HTTP API
  tests/           pytest
frontend/          React + TypeScript + Vite (mobil uyumlu)
database/          schema_postgres.sql (Supabase için)
docs/              rapor, veri erişimi, mimari, backtest çıktıları
HorseIQ_v0_2_paket/  önceki tek-HTML prototip (referans için korunuyor)
```

## Çalıştırma (Windows / macOS / Linux)

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip
.venv/Scripts/python -m horseiq.cli seed-demo       # isteğe bağlı: DEMO dünya (~8 dk)
.venv/Scripts/python -m uvicorn horseiq.api.app:app --port 8000
```

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (/api istekleri 8000'e yönlenir)
```

Testler: `cd backend && .venv/Scripts/python -m pytest -q`

## Gerçek veri içe aktarma

| Yol | Komut | Durum |
|---|---|---|
| **TJK "CSV Sonuçlar" (elle indirilen)** | `python -m horseiq.cli import-tjk-csv ../data_inbox/01.10.2026-Kocaeli-GunlukYarisSonuclari-TR.csv` | **Çalışıyor** — gerçek dosyayla doğrulandı |
| **TJK at koşu geçmişi (HorseIQ butonu)** | `python -m horseiq.cli import-tjk-horse %USERPROFILE%\Downloads` | Hazır — kurulum: `tools/tjk-kit/install.html` |
| **Accurace "Raporu indir" PDF'leri** | `python -m horseiq.cli import-accurace-pdf ../data_inbox/2026-10-01-kocaeli-1-summary.pdf ../data_inbox/2026-10-01-kocaeli-1.pdf` | **Çalışıyor** — OCR (Tesseract gerekir), gerçek raporla doğrulandı |
| TJK veri servisi (authKey) | `python -m horseiq.cli fetch-tjk --backfill-from 2023-10-27 --to 2026-10-25` | Anahtar gelince çalışır (en yeni günden geriye) |
| TJK JSON dışa aktarımı | `python -m horseiq.cli import-tjk-json dosya.json --results` | Hazır |
| Tarayıcıdan kaydedilen TJK sonuç sayfası | `python -m horseiq.cli import-tjk-html sayfa.html --date 2025-06-25 --track İstanbul` | Hazır, gerçek sayfa ile doğrulanmalı |
| Accurace takip verisi | `python -m horseiq.cli import-accurace kosu.json` | Format hazır, erişim bekleniyor |

Ayrıntılar ve hukuki notlar: [docs/DATA_ACCESS.md](docs/DATA_ACCESS.md).

## Geriye dönük test

```bash
python -m horseiq.cli backtest --world REAL --from 2026-01-01 --to 2026-10-25 --json ../docs/backtest/real.json
```

Rastgele seçim taban çizgisiyle birlikte raporlanır. Gerçek veride henüz çalıştırılamadı (veri yok).
