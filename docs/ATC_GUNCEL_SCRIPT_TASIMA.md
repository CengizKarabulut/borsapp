# ATC 2026-10-14 Pine → borsapp: tarama motoru değiştirme notu

## Yetkili kaynak

`docs/reference/ATC_TV200_18_TARAMA_20261012.pine` kullanıcının en güncel gönderdiği scriptin referans kopyasıdır. Orijinal Windows/Excel tarama ekranının eski "bilinmiyor" boş matrisini gerçek sinyal sanmayın.

**Kritik ayrım:** Pine kaynak dosyasında grafik üzerinde görünen eski `sigA..sigI` görsel tanımları hâlâ bulunur, fakat **alarmlara gönderilen 1–9 koşullar** `f_native_legacy_snapshot(atcBars)` fonksiyonu içinden üretilir. Güncel Python motoru bu native packet semantiğini esas alır. Eski görsel formülleri ve eski Python scanner sınıfları 1–9 için varsayılan taramada yürütülmez.

## Harita

| Pine native ID | Python scanner ID | Güncel kurallar |
|--|--|--|
| 1 A | signal.macd_positive_cross | MACD cross/rise + pozitif MACD + Wilder RSI14 > 30 |
| 2 B | signal.smi_macd_positive | Pozitif SMI, MACD histogram iyileşme; min 200 geçmiş mum |
| 3 C | signal.smi_macd_positive_volume_confirmed | B + SMA200 üstü + SMA20 dahil hacim 1.5x |
| 4 D | signal.ema_trend_volume | EMA21/55/200 üstü, üç EMA tetikleyicisi, hacim |
| 5 E | signal.rsi_macd_volume | Legacy RSI14 50 seviyesini geçme/yükselme, <70, MACD, hacim |
| 6 F | signal.sma_macd_volume | SMA5/8/21/50/55/200 üstü, MACD>0, tetik ve hacim |
| 7 G | signal.smi_macd_full | Negatif çekirdek, SMA200 üstü, hacim |
| 8 H | signal.smi_macd_early | Negatif çekirdek, tam G teyidi henüz oluşmadı |
| 9 I | signal.rsi_momentum_volume | Legacy RSI7 >60, eşik geçiş/yükseliş, 10 bar hacim |

Bu kurallar `scanning/signal/atc_native_packet.py` içinde **v2.0.0** olarak ayrıdır. Eşleşmelerde kaynak SHA tutulur, eski `v1.0.0` sonuçları geçmiş kayıtta kalabilir fakat yeni ruleset'in yerine geçmez.

**10–16:** Güncel Pine bu bölümü mevcut Python `scanning/technical/` kurallarından türetilen `f_r1016_snapshot` portu olarak sunuyor; var olan Python kodları mevcut kaynak mantığının dayanağı olduğu için şimdilik korunuyor.  
**17:** yalnızca 1D ve son teyitli günlük mum, `decision.panel_v645` mevcut temel Python yürütücüsü.  
**18:** geçmiş gözlemleriyle kalite onaylı MA sınıfları `research/ma_levels.py` ve `scanning/ma/near_zone.py` üzerinden. Ham MA yakınlığı kullanmak eşit değildir.

**Parite durumu:** Tam 18/18 TradingView-Python sayısal eşitliği henüz doğrulanmadı. 1–9 için eski alarm parity işaretleri yeni sürüme aktarılmadı; korunan `technical.volume_spike` 10 numaralı eski kanıtla sınırlı kalır. Kapanmamış mumla otomatik yayına başlamayın.

## 630 hisse / kaynak farkı

- `config/atc_630_symbols.txt`: ATC eski arşivindeki 630 benzersiz kod, güncel resmî liste olduğu **iddia edilmez**.
- `scripts/atc_universe_seed.py` BIST XUTUM provider ile fark raporu yazar ve isteğe bağlı `--apply` ile sadece **`ATC_630`** adında ayrı bir DB evreni oluşturur. Normal `BIST_ALL` etkilenmez.
- 2026-10-14 `universe-sync` (borsapy:XUTUM) **582** kod gözlemiştir. Eski 630 evrenindeki 48 ile aynı şirketler oldukları veya kesin fark listesinin ne olduğu doğrulanmadan yalnız sayı farkından teşhis koymayın.
- Veri sağlayıcıdan OHLCV alınamayan semboller `scan_cycle_failures` raporunda başarısız görünmelidir; gerçek sinyal üretilemez.

## GitHub otomasyonu

1. PR'ı inceleyip CI'da test edin; taslak PR ana dala henüz taşınmaz.
2. `ENABLE_ATC_630_UNIVERSE=true` ayarlanırsa var olan universe-sync işine 630 evreni kurma/denetleme eklenir. Önce tek sefer `scripts/atc_universe_seed.py` çalıştırılarak eksikler görülmeli.
3. `ATC_SCAN_UNIVERSE=ATC_630` kullanılarak mevcut `scheduled-scan.yml` ve `ma-research.yml` işlerinin aynı 630 hedef evrende çalışması sağlanır. Zaman dilimi altyapısı korunur. Yeni native kaynak için varsayılan analiz geçmişi **600** bardır.
4. GitHub `atc-cloud-report.yml`, bu evrenden **gerçekte kaydedilmiş** tarama değerlendirmelerini çıkarır. 630 üyeden azsa açık hata verir; en az %95 güncel doğrulama olmadan Telegram günlük raporu kuyruğa alınmaz.
5. En son `ENABLE_SCHEDULED_SCANS=true`, `ENABLE_SCHEDULED_RESEARCH=true`, `ENABLE_ATC_CLOUD_REPORT=true` değişkenleri, veri akışı ve GitHub Action süreleri test edildikten sonra açılır.
6. Telegram `SCAN_DELIVERY_MODE=shadow` ve `ATC_REPORT_DELIVERY_MODE=shadow` ile başlar; parite ve doğru konu yönlendirme testi olmadan `live` yapılmaz.

## İzleme / değerlendirme

Gerçek sonuç = `scan_evaluations.status=match` + `scan_events` yönlü delil. Aynı mum ve farklı kaynak sürümleri ayrı değerlendirmelerdir; başka mumdan gelen veri birleştirilmez. `VERI_YOK` / `KOSUL_YOK` / `SURUM_UYUSMAZLIGI` / `HESAPLANAMADI` statüleri birbirinin yerine kullanılamaz.

**Henüz yapılmayan işler:** 630 hisseyle uçtan uca canlı tarama, 10–18 aynı-veri sayısal parity, 630/582 sembol eşleştirme, ücretsiz/uygun fiyat verisi sağlayıcısında kota/kapasite ölçümü, ATC web dashboard yayımlama, Telegram live pilot.
