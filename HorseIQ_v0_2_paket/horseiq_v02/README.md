# HorseIQ v0.2 — çevrimdışı prototip

`index.html` dosyasını Chrome/Edge ile açın. Sunucu gerekmez. Tarayıcı veriyi uzak bir sunucuya yollamaz.

- Hazır gelen 25 Ekim 2026 İstanbul 1–3. koşularının **yalnızca at isimleri ve temel program bilgileri**, kamuya açık yarış programından elle örnek olarak alınmıştır. Resmî canlı TJK bağlantısı yoktur.
- Hız, tempo ve dayanıklılık verileri **sentetiktir**. Gerçek tahmin veya kazanma olasılığı değildir.
- Kendi verinizi denemek için önce `ornek_program.json`, ardından `ornek_performans.json` yükleyin. Her iki örnek dosyasındaki at kimlikleri eşleşir. Bu iki dosyadaki atlar ve hızlar da kurgusaldır.
- Geçmiş performans kayıtları `performances` dizisidir. Her kayıtta `horseId` (veya `horseName`), `date`, `track`, `surface`, `distance`, `early`, `mid`, `finish` gerekir. Hızlar metre/saniyedir; ilk, orta ve son bölümün yaklaşık hızlarıdır. Kaynakta bu alanlar mevcut değilse dönüştürücü geliştirilmesi gerekir.
- Filtre: 400 gün; son 3 uygun yarış; aynı hipodrom, aynı pist türü, mesafe ±200 metre. 30–1095 gün ve 1/2/3/5/10 yarış seçenekleri.
- Müdahale motorunda startta kalma, önü kapanma, sprinte geç başlama ve trafik var. Simülasyon arka plan etkileri kaba araştırma hipotezleridir, ölçülmüş katsayılar değildir. Modelin doğruluğu henüz test edilmedi.

## Bir sonraki entegrasyon
1. TJK için izinli program JSON/API erişimi.
2. Accurace izinli geçmiş yarış verisi; veri türü ve at kimliklerini eşleyen dönüştürücü.
3. Geçmiş yarışları tarih sırasıyla test edip modelin doğruluğunu ölçme.
4. Ölçüm yoksa `demo` statüsünü koruma; gerçek tahmin iddiasında bulunmama.
