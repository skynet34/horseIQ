# HorseIQ TJK Kiti

TJK at sayfalarındaki koşu geçmişini, sayfayı açan kişinin tek tıklamasıyla JSON dosyasına çeviren yer imi butonu.

**Kurulum:** `install.html` dosyasını Chrome'da aç, "HorseIQ kaydet" butonunu yer imi çubuğuna sürükle.

**Kullanım:**
1. tjk.org → Günlük Yarış Sonuçları → hipodrom → **HorseIQ kaydet**: sağda koşuların atları ve at sayfası bağlantıları listelenir.
2. Bir atı aç (Tüm Yıllar, filtre yok) → **HorseIQ kaydet** → `tjk-at-<AtId>-<İSİM>.json` İndirilenler'e iner.
3. `cd backend` → `.venv\Scripts\python -m horseiq.cli import-tjk-horse %USERPROFILE%\Downloads`

**Neyi yapmaz:** TJK'ya kendi başına istek göndermez, sayfa dolaşmaz, toplu indirme yapmaz (tjk.org robots.txt otomatik
erişimi yasaklıyor). Yalnızca ekranda açık olan tabloyu okur.

**Dosya biçimi:** `{kind, kit_version, at_id, name, info{İsim, Yaş, Doğ. Trh, Baba, Anne…}, filters[], header[], rows[{cells[], links[]}]}`.
Hücreler ham metin olarak kaydedilir; yorumlama `backend/horseiq/collectors/tjk/horse_history.py` içinde.
TJK sayfa düzeni değişirse önce Python tarafı güncellenir; buton yalnızca "Tarih" ve "Derece" başlıklı tabloyu arar.

**Geliştirme:** `horseiq-kaydet.js` değişince `python tools/tjk-kit/build.py` (install.html yeniden üretilir).
Test: `node tools/tjk-kit/test/run_kit.js tools/tjk-kit/install.html` (Playwright gerekir) — `test/` içindeki
sayfalar ekran görüntüsünden yapılmış taklitlerdir; gerçek TJK HTML yapısıyla birebir aynı olmayabilir.
