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

## Elle kaydedilen TJK sayfaları (bugün kullanılabilir, küçük ölçek)

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
