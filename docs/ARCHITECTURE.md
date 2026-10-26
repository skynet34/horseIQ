# Mimari

```
TJK API / kaydedilmiş sayfa / Accurace JSON / DEMO üretici
        │  (collectors: kaynak → domain.RaceRecord / HorseTrackingRecord)
        ▼
importer.Importer  ── tek yazma yolu: tekrar yok, kaynak kimliğiyle at eşleştirme,
        │             koşmaz takibi, REAL/DEMO ayrımı, import_logs raporu
        ▼
DB (SQLite / PostgreSQL)  races · race_entries · race_results · horses · horse_source_ids · jockeys
                           horse_performances · sectional_times · horse_tracking_points
                           simulation_runs · simulation_results · import_logs
        │
        ▼
form.history.load_runs → select_history (sızıntı kesimi → filtre → yeni→eski → Mod A veya Mod B)
form.speed_model.fit    (yalnızca hedef tarihten önceki koşularla) → hız figürü (z)
form.scoring            → form puanı + SimProfile (cruise_speed, early_pref, kick, stamina, ...)
        │
        ▼
sim.engine.simulate     zaman adımlı (dt 0.2 sn), at başına bağımsız rastgele akış
sim.montecarlo          n tekrar → kazanma / ilk üç sıklığı
backtest.runner         kronolojik test, rastgele taban çizgisiyle
api.app (FastAPI)  ◄──  frontend (React)
```

## Yarış motoru (sim/engine.py)

- **Enerji:** E=1 ile başlar; v hızında tüketim `(v/vc)^3 · vc / D`. vc hızında baştan sona koşan at enerjisini tam çizgide bitirir. Kalan mesafede sürdürülebilir hız `vc·√(E·D/kalan)`.
- **Kalibrasyon:** Profildeki hız gerçek bitiriş derecelerinden gelen *ortalama* hızdır (start dahil). Motor, at tek başına koşunca `mesafe / ortalama hız` süresini verecek şekilde vc'yi ölçekler (testle doğrulanır, %1).
- **Sprint:** finiş rezervi (kick) yalnızca son bölümde açılır; sprint öncesi jokey planlı tempoyu korur (tasarruf edilen enerji ancak sprintte kullanılır); fizyolojik azami hız sınırı var.
- **Liderlik mücadelesi:** liderin 1,5 boy yakınında, önde koşmayı seven (early_pref) en az iki at → tempo artışı + %8 ek enerji; jokey olasılıkla geri çekilir.
- **Trafik:** aynı şeritteki öndeki atın içinden geçilemez; dışa/içe boşluk aranır, yoksa öndeki atın hızına kilitlenir ("sıkıştı" olayı). Virajda dış şerit fazladan yol demektir (R/(R+şerit)).
- **Rakibe cevap:** son 800 m'de yakındaki atın atağına erken sprintle cevap verme (rezervin bir kısmı boşa gider).
- **Müdahaleler:** startta kaldı, önü kapandı, sprinte geç başladı, trafiğe takıldı; zamanlama başlarda / son virajda / son düzlükte. Müdahale biten ata yalnızca süre eklemez: at yavaşlar, arkasındakileri tıkar, açılınca yanındakileri sıkıştırır; tüm yarış yeniden hesaplanır.
- **Aynı şans:** her atın rastgele akışı (seed, at) ile tohumlanır ve her adımda aynı sayıda çekilir; normal ve müdahaleli yarış aynı tohumla koşar.

`ASSUMED` işaretli katsayılar (boy ≈ 2,4 m, pist geometrisi, düello maliyeti, rezerv, kilo etkisi 0,02 m/s/kg ...) ölçülmemiştir; gerçek veriyle kalibre edilecektir.

## Form

- Mod A (gün, varsayılan 400) ve Mod B (son N uygun koşu, varsayılan 3) birbirinden bağımsızdır.
- Filtre sırası: tarih < yarış günü → hipodrom → pist → mesafe ±tolerans → en yeniler → mod.
- Güncellik ağırlığı: son 3 koşu 50/30/20, sonrası ×2/3; gün modunda ek olarak 1 yıllık yarı ömür.
- Bileşenler (başlangıç ağırlıkları): hız %30, finiş %25, tempo dayanıklılığı %15, fazladan yol %10, rakip/sonuç %10, eğilim %10. Hesaplanamayan bileşen (ör. ara derece yokken finiş, takip yokken fazladan yol) atlanır ve ağırlıklar yeniden dağıtılır — uydurulmaz.

## Sonraki teknik işler

- İçe aktarma hızı: SQLite'ta satır satır upsert; 3 yıllık arşiv için toplu (bulk) yazma eklenmeli.
- Motor hızı: ~0,3 sn/yarış (12 at). Monte Carlo için süreç havuzu var (`workers`); daha hızlısı için NumPy vektörleştirme.
- Hipodrom geometrisi (`racetracks.home_straight_m`, `turn_radius_m`) gerçek değerlerle doldurulmalı.
- Jokey/antrenör etkisi, start kulvarı etkisi, pist durumu → veri gelince.
