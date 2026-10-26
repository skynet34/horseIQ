# Veri erişimi — durum ve kurallar (26 Ekim 2026)

## Özet

| Kaynak | Otomatik erişim | HorseIQ'da durum |
|---|---|---|
| tjk.org (web sayfaları) | **Yasak** — robots.txt: `User-agent: * Disallow: /`; ayrıca `Claude-User`, `ClaudeBot`, `GPTBot`, `ChatGPT-User` vb. adıyla engelli | Taranmıyor. Elle kaydedilen sayfalar içe aktarılabilir. |
| TJK veri servisi (`vhs.tjk.org/vss/data`, `X-Auth` anahtarı) | Yalnızca TJK'nın verdiği anahtarla | Adaptör hazır, anahtar yok → kapalı |
| `ebayi.tjk.org/s/d/` (SezerFidanci/TJK-API'nin kullandığı bayi beslemesi) | Bayi beslemesi; kamuya açık kullanım izni belirsiz | Kullanılmıyor |
| accurace.net | `Disallow: /network/*` (yarış sayfaları) | Taranmıyor. İçe aktarma formatı ve modül hazır. |
| Accurace API | Lisans gerektirir | Talep gönderildi, yanıt bekleniyor |

HorseIQ hiçbir korumayı aşmaz, anahtar tahmin etmez veya başkasının anahtarını kullanmaz.
Geliştirme sırasında robots.txt okunmadan önce tjk.org'dan **2 sayfa** (ana sayfa ve günlük sonuçlar giriş sayfası) bir kez indirildi; yalnızca yapı incelemesi için kullanıldı, depoya konmadı. Sonrasında tjk.org'a istek yapılmadı.

## TJK'dan resmî erişim için yapılması gerekenler

1. TJK'ya (Bilgi İşlem / Kurumsal İletişim) yazılı başvuru: amaç (yarışseverlere sanal yarış/analiz uygulaması), istenen veri (günlük program, sonuçlar, son 3 yıl arşiv), kullanım şekli (ticari mi?), ve **TJK veri servisi anahtarı** (`X-Auth`).
2. Ticari kullanım, veri yeniden yayımı ve at/jokey isimlerinin gösterimi için yazılı izin/sözleşme. TJK sitesinin kullanım koşulları ve robots.txt otomatik toplamaya izin vermiyor; ticari ürün için lisans şart kabul edilmeli.
3. Anahtar gelince: `backend/.env` → `TJK_AUTH_KEY=...`, sonra
   `python -m horseiq.cli fetch-tjk --backfill-from 2023-10-27 --to <dün>` (en yeni günden geriye, 2 sn aralıkla).

Servis alan adları `bilaleren/tjk-api` (MIT) kaynak kodundan doğrulandı: `program`, `sonuclar`, `jokey-degisiklikleri`, `at-detay`, `hipodromlar`; tarih `dd/MM/yyyy`, hipodrom `hipodromkey`. Alanlar: `yarislar[].kosular[].atlar[]` → `KEY, NO, AD, YAS, START, SONUC, DERECE, FARK, KILO, JOKEYADI, KOSMAZ, BABA, ANNE ...`.

## Elle indirilen dosyalar (26 Ekim 2026'dan itibaren ana yol)

TJK ve Accurace, sayfalarında herkesin indirebileceği dışa aktarımlar sunuyor. HorseIQ bu siteleri
taramaz; dosyaları bir kişi kendi tarayıcısından indirir ve `data_inbox/` klasörüne koyar.

**TJK "CSV Sonuçlar"** (`collectors/tjk/csv_results.py`, `import-tjk-csv`). Bir gün + bir hipodrom = bir dosya.
Doğrulanmış biçim (01.10.2026 Kocaeli, 10 koşu, 106 at): `;` ayraçlı, UTF-8 BOM. Dikkat edilecekler:
- **"At No" sütunu bitiriş sırasıdır, program numarası değil.** CSV'de program no ve TJK at kimliği yok;
  kazananın program no'su GANYAN satırından, diğerleri Accurace raporundan gelir.
- At eşleştirme isim + doğum yılı + baba + anne ile yapılır (kimlik yok). Aynı isim farklı pedigri → ayrı at.
- At ismine eklenen ekipman kodları (KG, DB, SK, K, GKR …) atılır; "57 +0.60" = 57,60 kg (fazla kilo);
  "11 - DS" = 11. kulvar, dış start; "Derecesiz" → DNF; AGF ve ganyan şimdilik saklanmıyor.

**TJK at koşu geçmişi** (`tools/tjk-kit`, `collectors/tjk/horse_history.py`, `import-tjk-horse`). At sayfasında
(AtKosuBilgileri) yer imi butonuna basılınca ekrandaki tablo JSON olarak iner. Buton sunucuya istek atmaz.
- Her satır, yalnızca bu atın bilindiği *kısmi* bir koşu olur: diğer atlar koşmaz işaretlenmez, CSV'den gelen
  koşu bilgileri (sınıf, pist durumu …) ezilmez; aynı koşu CSV'den de geldiyse at o koşuya eklenir.
- At, TJK at kimliğiyle (AtId) kaydedilir; CSV'den isimle gelen aynı at (isim + doğum yılı + baba + anne) bu kimliği alır.
- Kısmi koşularda saha büyüklüğü bilinmez; form motorunun "rakip/sonuç" bileşeni bu koşuları atlar.
- Taklit sayfayla test edildi; gerçek TJK sayfasıyla ilk kullanımda sütun/başlık eşlemesi kontrol edilmeli.

**Accurace "Raporu indir" PDF'leri** (`collectors/accurace/pdf_report.py`, `import-accurace-pdf`).
PDF'in içinde tek bir ekran görüntüsü var (metin yok), bu yüzden Tesseract OCR ile okunur.
- *summary* raporu: her atın 400 m, 600 m, …, bitişteki kümülatif süresi ve o noktadaki sırası → `sectional_times`.
- *detay* raporu: seçili bölüm (varsayılan son 100 m) süresi, bariyere uzaklık, bölüm hızı; tüm koşu için
  koşulan toplam mesafe (fazladan yol), ortalama hız, kazanana göre mesafe farkı → `horse_performances`
  (bariyer/delta/fark `extra` alanında). Maksimum hız raporda 0,0 göründüğü için kaydedilmiyor.
- Her sayı çapraz kontrol edilir (ara dereceler artmalı, sıra süreyle uyumlu olmalı, başlıktaki lider
  süresi = en iyi süre, bölüm süresi = ara derece farkı, ortalama hız = mesafe / süre, iki raporun
  bitiriş süresi aynı). Tutmayan değer atılır ve raporlanır; tahmin edilmez.
- Program numarası rozetten OCR ile, olmazsa rozet renginden okunur (renk eşlemesi 1–8, 10, 11 için var).
- Accurace bitiriş süreleri resmî dereceden ~0,25 sn farklıdır (Accurace hasa bezi, TJK foto finiş
  burun referansı alıyor). Resmî derece her zaman TJK CSV'den gelir.

Ölçek: bir koşu için 2 PDF, bir gün için hipodrom başına 1 CSV. Geçmiş arşivi bu yolla toplamak zahmetli;
TJK veri servisi anahtarı hâlâ en iyi uzun vadeli çözüm.

## Elle kaydedilen TJK sayfaları (küçük ölçek)

Bir kişi kendi tarayıcısında "Günlük Yarış Sonuçları" sayfasını açıp hipodromu seçer, sonuç tabloları görünür hâldeyken **Ctrl+S** ile kaydeder:

```bash
python -m horseiq.cli import-tjk-html "25-06-2025 Istanbul.html" --date 2025-06-25 --track İstanbul
```

Ayrıştırıcı tabloları başlık satırından (At İsmi, Jokey, Derece, Fark, St …) tanır, at kimliğini bağlantıdaki `AtId` parametresinden alır.
**Not:** Gerçek bir kaydedilmiş sayfayla henüz doğrulanmadı (tjk.org'dan sayfa çekmedik). İlk gerçek dosyada okunamayan satırlar içe aktarma raporunda listelenir; gerekirse sütun eşlemesi `HEADER_MAP` içinde güncellenir.
Bu yol, 3 yıllık arşiv için uygun değildir; yalnızca birkaç günlük doğrulama seti içindir. Kullanım koşulları bakımından da kişisel/araştırma ölçeğinde tutulmalıdır.

## Accurace JSON (değişim formatı)

```json
{"date": "2026-10-18", "track": "ISTANBUL", "race_no": 1,
 "horses": [{"accurace_id": "A123", "name": "AT ADI", "program_no": 3,
             "total_distance_m": 1412.5, "avg_speed_mps": 16.1, "max_speed_mps": 18.0,
             "sectionals": [{"from_m": 0, "to_m": 200, "time_s": 12.9, "position": 2}],
             "points": [{"t_ms": 0, "distance_m": 0, "lat": 41.0, "lon": 28.8, "speed_mps": 0,
                         "rail_distance_m": 1.2, "position": 4}]}]}
```

Koşunun önce TJK'dan içe aktarılmış olması gerekir; at önce Accurace kimliğiyle, yoksa program numarasıyla eşleşir. API gelince yalnızca `AccuraceClient.race()` yazılacak; veri modeli, form motoru (finiş gücü, fazladan yol, gerçek koşu stili) ve simülatör bu veriyi zaten kullanıyor (`REAL` olarak işaretlenir).

Accurace'in kendi sayfası TJK için 10 hipodromda (İstanbul, Ankara, İzmir, Antalya, Adana, Bursa, Kocaeli, Diyarbakır, Şanlıurfa, Elazığ) çalıştığını söylüyor; 2023 başlangıç tarihini bağımsız bir kaynaktan doğrulayamadık.

## Veri durumları

- **REAL** — resmî sonuç / ölçülmüş ara derece.
- **ESTIMATED** — gerçek sonuçlardan türetilmiş ama ölçülmemiş (ör. bitiriş derecesinden hız figürü, mesafe tercihinden koşu stili, kazanan derecesi + boy farkından türetilen derece).
- **DEMO** — tamamen sentetik. İsimleri `DEMO` ile başlar; ayrı "Demo" modunda gösterilir; içe aktarıcı REAL koşuyla birleştirmeyi reddeder.
- Arayüzde ayrıca **NO_DATA**: filtreye uyan geçmiş koşusu olmayan at (varsayımsal profil, açıkça etiketli).
