# data_inbox

Tarayıcıdan **elle** indirilen kaynak dosyalarını buraya koyun. Bu klasördeki .csv/.pdf/.html/.json
dosyaları git'e eklenmez (TJK ve Accurace içeriği depoda yeniden yayımlanmaz).

| Ne | Nereden | Dosya adı (indirildiği gibi) |
|---|---|---|
| TJK günlük sonuçlar | tjk.org → Günlük Yarış Sonuçları → hipodrom → **CSV Sonuçlar** | `01.10.2026-Kocaeli-GunlukYarisSonuclari-TR.csv` |
| TJK at koşu geçmişi | at sayfası → yer imi çubuğundaki **HorseIQ kaydet** (`tools/tjk-kit/install.html`) | `tjk-at-112812-DIREN-KAPORTACI.json` |
| Accurace ara dereceler | accurace.net → koşu → *summary* sayfası → **Raporu indir** | `2026-10-01-kocaeli-1-summary.pdf` |
| Accurace detay (bariyer, koşulan mesafe) | accurace.net → koşu sayfası → **Raporu indir** | `2026-10-01-kocaeli-1.pdf` |

Sıra önemli: önce o günün TJK CSV'si, sonra Accurace PDF'leri (atlar TJK kaydıyla eşleştirilir).

```bash
cd backend
.venv/Scripts/python -m horseiq.cli import-tjk-csv ../data_inbox/01.10.2026-Kocaeli-GunlukYarisSonuclari-TR.csv
.venv/Scripts/python -m horseiq.cli import-tjk-horse ../data_inbox          # klasördeki tüm tjk-at-*.json
.venv/Scripts/python -m horseiq.cli import-accurace-pdf ../data_inbox/2026-10-01-kocaeli-1-summary.pdf ../data_inbox/2026-10-01-kocaeli-1.pdf
```

`import-accurace-pdf` önce OCR sonucunu PDF'in yanına `.accurace.json` olarak yazar ve bulduğu
tutarsızlıkları listeler; `--dry-run` ile veritabanına yazmadan yalnızca kontrol edebilirsiniz.
Accurace PDF'i bir ekran görüntüsüdür; okumak için Tesseract OCR kurulu olmalı
(Windows: https://github.com/UB-Mannheim/tesseract/wiki, ya da `TESSERACT_CMD` ile yolunu verin).
