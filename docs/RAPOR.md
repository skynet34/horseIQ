# HorseIQ — İlerleme Raporu

**Tarih:** 26 Ekim 2026 · **Sürüm:** v0.4 (motor 0.4.0) · **Depo:** https://github.com/skynet34/horseIQ

## Kısa özet

- Tek HTML prototip (v0.2), modüler bir ürüne taşındı: Python/FastAPI backend + veritabanı + React/TypeScript arayüz.
- **Gerçek TJK verisi toplanamadı.** tjk.org robots.txt ile tüm botlara ve adıyla Claude/ChatGPT ajanlarına otomatik erişimi yasaklıyor; TJK veri servisi anahtar (authKey) istiyor; accurace.net yarış sayfalarını robots.txt ile kapatıyor. Koruma aşmadım. Bunun yerine veri gelir gelmez çalışacak üç içe aktarma yolu hazırladım (aşağıda).
- Form motoru, etkileşimli yarış motoru, 4 müdahale, animasyon, sonuç/boy farkı, Monte Carlo ve geriye dönük test **çalışıyor** — şu an yalnızca açıkça işaretli **DEMO** (sentetik) veriyle denenebiliyor.
- 23 otomatik test geçiyor. Arayüz uçtan uca (yarış seç → koştur → sonuç → müdahale → karşılaştırma) tarayıcıda denendi.

> Not: Klasörde **v0.3 yoktu**, yalnızca `HorseIQ_v0_2_paket` vardı. v0.2'nin işlevleri (hipodrom/pist/mesafe filtreleri, gün ve yarış sayısı modları, 4 müdahale, normal/müdahaleli karşılaştırma, derece ve sıralama, JSON yükleme yerine CLI içe aktarma) yeni mimaride korunup genişletildi. v0.3'teki ek özellikler (yarış hızı ayarı, boy farkı) ayrıca yeni sürümde mevcut. v0.3 dosyasını eklerseniz farkları kontrol ederim.

## Aşama aşama durum

| Aşama | Durum | Not |
|---|---|---|
| 1. Prototip incelemesi | ✅ | v0.2 incelendi; sentetik hız profilleri ve kalibre edilmemiş katsayılar tespit edildi |
| 2. TJK veri toplayıcı | ⚠️ Kod hazır, **veri yok** | Erişim engeli — bkz. [DATA_ACCESS.md](DATA_ACCESS.md) |
| 3. Gerçek form hesabı | ✅ (DEMO ile test edildi) | Mod A / Mod B bağımsız, filtreler, sızıntı koruması, hız normalizasyonu |
| 4. Yarış motoru | ✅ ilk sürüm | Enerji, liderlik mücadelesi, trafik/kutulanma, viraj kaybı, rakibe cevap |
| 5. Müdahaleler | ✅ | 4 olay × 3 zamanlama, aynı şansla yeniden hesap, diğer atlar etkileniyor |
| 6. Animasyon ve sonuçlar | ✅ | Oval pist + fark şeridi, 1×–10× (sonucu değiştirmez), derece, boy farkı, mobil |
| 7. Geriye dönük test | ⚠️ Yalnızca DEMO | Gerçek veri olmadan model doğruluğu ölçülemez |

## Hangi gerçek veri toplandı?

**Hiç.** Veritabanında 0 gerçek koşu, 0 gerçek at var. (Geliştirme sırasında robots.txt okunmadan önce tjk.org'dan yalnızca 2 sayfa yapı incelemesi için indirildi; içindeki veri kullanılmadı, depoya konmadı.)

DEMO dünya (yalnızca test için): 4.361 koşu, 41.252 sonuç, 180 hayalî at (isimleri `DEMO` ile başlar), Ocak 2025 – Ekim 2026, İstanbul/Ankara/İzmir adları altında. DEMO veritabanı depoya konmadı; `python -m horseiq.cli seed-demo` ile yeniden üretilir.

## Şu anda gerçekten çalışanlar

- **İçe aktarma:** tekrarsız (aynı koşu güncellenir), TJK at kimliğiyle eşleştirme (isim yalnızca yedek ve raporlanır), koşmaz takibi, geçersiz derece/mesafe raporu, REAL–DEMO karışmasını reddetme, `import_logs`.
- **TJK authKey adaptörü:** alan adları açık kaynak istemciden doğrulandı; örnek yükle test edildi. Gerçek servise hiç bağlanılmadı (anahtar yok).
- **Kaydedilmiş sayfa ayrıştırıcı:** sentetik örnek sayfayla test edildi; **gerçek TJK sayfasıyla doğrulanmadı.**
- **Form:** son 400 gün / son N koşu; aynı hipodrom, aynı pist, ±200 m varsayılan; önce filtre sonra son N; yarış gününden önceki veriler; mesafe/pist/hipodrom/pist durumuna göre normalize edilmiş hız figürü; bileşen bazlı açıklanabilir puan.
- **Motor:** testlerle doğrulanan davranışlar — tek başına koşan atın süresi profiline %1 içinde uyuyor; atlar birbirinin içinden geçmiyor; aynı tohum aynı sonucu veriyor; 3 önde koşan at düello yaptığında ortalamada geriye düşüyor (geriden gelenler avantajlı); her müdahale ilgili atı yavaşlatıyor ve senaryoların önemli kısmında diğer atların sonucunu da değiştiriyor.
  Örnek (DEMO, Ankara 1. koşu): 3 numara son virajda trafiğe takıldı → arkasındaki 1 numara kutulandı ve 3 dışa açılırken sıkıştı → 6 numara 4.'lükten 3.'lüğe yükseldi, 1 numara 3.'lükten 4.'lüğe düştü.

## Tahmini / varsayımsal olanlar (açıkça)

- Ara derece olmadığı için koşu stili (önde/geride), finiş gücü ve dayanıklılık **ESTIMATED**: koşu stili, atın kısa mesafelerde mi uzun mesafelerde mi daha iyi olduğundan türetilen zayıf bir vekil.
- Motor katsayıları (düello maliyeti, finiş rezervi, azami hız, kilo etkisi 0,02 m/s/kg, 1 boy ≈ 2,4 m, pist geometrisi 400 m son düzlük / 110 m viraj yarıçapı) **ASSUMED** — ölçülmedi.
- Start becerisi tüm atlar için varsayılan (TJK "geç çıkış" alanı ileride kullanılabilir).
- Filtreye uyan geçmişi olmayan at **"veri yok"** olarak etiketlenir ve sahanın ortanca hızının biraz altında, varsayımsal profille koşar.

## Geriye dönük test sonucu (yalnızca DEMO — gerçek doğruluk değildir)

Dönem: 1 Eylül – 25 Ekim 2026, 367 DEMO koşu, kronolojik, sızıntısız. Dosya: [backtest/demo_backtest_2026-09_10.json](backtest/demo_backtest_2026-09_10.json)

| Ölçüt | Rastgele | Form sıralaması | Tek simülasyon | Monte Carlo (12) |
|---|---:|---:|---:|---:|
| Birinciyi bilme | %10,9 | %58,0 | %45,5 | %54,5 |
| Gerçek birinci sanal ilk 3'te | %32,6 | — | %77,7 | — |
| Sıralama korelasyonu (Spearman) | 0 | 0,73 | 0,65 | — |
| Kazanan derecesi mutlak hata | — | — | 1,19 sn | — |
| Boy farkı mutlak hata | — | — | 12,4 boy | — |

**Nasıl okunmalı:** DEMO sonuçları, gizli yetenekleri bilinen sentetik atlardan, HorseIQ motorundan bağımsız basit bir modelle üretildi. Bu test yalnızca *hattın* (içe aktarma → form → simülasyon) ekilen sinyali geri bulabildiğini gösterir. DEMO dünyasında tempo etkileşimi olmadığı için yarış motorunun etkileşimleri burada yalnızca gürültü ekliyor; bu yüzden tek simülasyon form sıralamasından kötü. **Gerçek yarışlarda tahmin gücü hakkında hiçbir şey söylemez.** Boy farkı hatası büyük (12 boy); bu DEMO'daki yüksek rastgelelikten kaynaklanıyor olabilir ama gerçek veriyle ilk kontrol edilecek konu bu olmalı.

## Engeller

1. **TJK erişimi (kritik):** robots.txt otomatik toplamayı yasaklıyor; veri servisi anahtar istiyor; ticari kullanım için izin gerekli. → TJK'ya resmî başvuru (metin önerisi DATA_ACCESS.md'de).
2. **Accurace:** lisans/anahtar bekleniyor. Modül ve veri modeli hazır.
3. **İçe aktarma hızı:** 4.361 koşu ~8 dk (SQLite, satır satır). 3 yıllık gerçek arşiv için toplu yazma eklenmeli.
4. **Motor hızı:** ~0,3 sn/yarış; 1.000 tekrarlı Monte Carlo ~5 dk. Şimdilik arayüzde gösterilmiyor (spesifikasyon gereği), API'de var.

## Sizden gerekenler

1. TJK veri servisi anahtarı ve kullanım izni için başvuru (en kritik adım).
2. Hızlı doğrulama için: tarayıcınızda birkaç günün "Günlük Yarış Sonuçları" sayfasını (sonuç tabloları açıkken) Ctrl+S ile kaydedip `data_inbox/` klasörüne koyun → ayrıştırıcıyı gerçek sayfayla doğrularım ve ilk gerçek yarışı yeniden koştururuz.
3. Accurace yanıtı gelince API dokümanı.
4. v0.3 dosyası varsa ekleyin.

## Evde çalıştırma

```bash
git clone https://github.com/skynet34/horseIQ.git
cd horseIQ/backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m horseiq.cli seed-demo          # ~8 dk, DEMO veritabanı
.venv/Scripts/python -m uvicorn horseiq.api.app:app --port 8000
# ikinci terminal
cd horseIQ/frontend && npm install && npm run dev      # http://localhost:5173 → "Demo"
```

## Sonraki adımlar (öncelik sırasıyla)

1. Gerçek veri gelir gelmez: içe aktarma → ilk gerçek geçmiş yarışı o tarihten önceki kayıtlarla yeniden koşturma (ilk büyük hedef) → gerçek backtest.
2. Motor katsayılarını gerçek sonuçlarla kalibre etme (kazanan derecesi, boy farkı dağılımı, önde koşanların başarı oranı).
3. Toplu içe aktarma ve günlük program otomatik güncelleme (koşmaz / jokey değişikliği).
4. Hipodrom geometrileri, start kulvarı etkisi, jokey etkisi.
