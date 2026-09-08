# borsapp

borsapp; teknik sinyal, hareketli ortalama, araştırma, grafik ve haber
uygulamalarını tek veri ve teslimat altyapısında birleştiren Market Intelligence
Suite deposudur.

Proje şu anda kontrollü göç aşamasındadır. Dört kaynak depo "_legacy/" altında
korunur; yeni kod "src/market_intelligence/" içinde, davranış parity testleriyle
aile aile devreye alınacaktır.

## Değişmez mimari sınırlar

- Scanner veri çekmez, Telegram'a yazmaz ve sistem saatini doğrudan okumaz.
- İndikatörler ortak feature katmanında, açık implementasyon ve warmup kimliğiyle hesaplanır.
- Event ile state farklı saklanır; MATCH, NO_MATCH ve UNKNOWN aynı şey değildir.
- Canonical kimlik ticker değil instrument_id değeridir.
- Kapanmamış veya kısmi mum varsayılan olarak sinyal üretemez.
- Confluence puan veya yatırım tavsiyesi değil, zaman pencereli kesişim bilgisidir.
- Telegram tek listener ve transactional outbox üzerinden çalışır.
- Legacy davranış shadow modda doğrulanmadan kapatılmaz.

Ayrıntılı sözleşme: [docs/architecture/frozen-contract.md](docs/architecture/frozen-contract.md)

## Kaynak depolar

| Kaynak | Geçici konum | Hedef rol |
| --- | --- | --- |
| taramabot | _legacy/taramabot | SIGNAL ve KARAR taramaları |
| ma-reaction-scanner | _legacy/ma-reaction-scanner | MA Live ve MA Research |
| market-telegram-suite | _legacy/market-telegram-suite | TECHNICAL, araştırma ve grafik |
| tradingview-haber-botu | _legacy/tradingview-haber-botu | Haber, KAP, takvim ve bülten |

## Yerel doğrulama

    python -m pip install --editable ".[dev]"
    python -m unittest discover -s tests -v
    python scripts/audit_purity.py --root _legacy --output docs/migration/purity-audit.json
    python scripts/map_indicators.py --root _legacy --output docs/migration/indicator-map.json
    python scripts/build_migration_inventory.py --root _legacy --output docs/migration/file-inventory.csv

PostgreSQL geliştirme servisi:

    docker compose up -d postgres

Kullanıcı kurulumları:

- [Telegram forum ve topic kurulumu](docs/setup/telegram.md)
- [GitHub Actions ve repo ayarları](docs/setup/github.md)
- [Çalıştırma, shadow ve canlıya geçiş](docs/setup/operations.md)

Tarayıcı kuralları [config/scanners.toml](config/scanners.toml), MACD referans
kararı ise [ADR-0001](docs/adr/0001-macd-reference-implementation.md) içindedir.
Katalog bugün 9 SIGNAL, 7 TECHNICAL, 1 MA ve 1 KARAR tarayıcısı içerir. Bu sayı, parity
kanıtı veya legacy'nin kaldırıldığı anlamına gelmez; aşağıdaki tablo bu ayrımı
açıkça gösterir.

## Güncel göç durumu

| Alan | Çalışan durum | Kalan doğrulama / göç |
| --- | --- | --- |
| SIGNAL | 9 scanner canonical motor üzerinde; gerçek legacy shadow adapterleri hazır | Saha parity örnekleri ve scanner bazlı promosyon |
| TECHNICAL | Legacy screener'daki 7 ekran canonical motor ve gerçek legacy shadow adapterleri üzerinde | Saha parity örnekleri; grafik vendor kodunun ayrıştırılması |
| MA | Live state, günlük research seviyeleri, ortak cache'lenen ATR ve gerçek MA Live shadow adapter | MA Research için ayrı saha parity kanıtı |
| Telegram | Tek bot, topic routing, listener, outbox ve uzun iş kuyruğu | Kalıcı hosta geçiş ve sağlık gözlemi |
| Haber | KAP canonical; genel haber compatibility adapteriyle çalışıyor | Genel haber kaynaklarını legacy importundan kurtarma |
| Veritabanı | Sıralı/checksum'lı migration runner, gerçek PostgreSQL CI testi | Üretim yedekleme prosedürü |
| KARAR | `decision.panel_v645` canonical günlük scanner ve gerçek legacy shadow adapter üzerinde | Saha parity örnekleri ve promosyon |
| Araştırma | `/analiz` tek ekran canonical özet; `/rapor` 24 bölümlü PDF; `/temel` ortak finansal provider zinciri | MTF/Elliott feature'ları ve saha veri kapsamı |
| Sonuç ölçümü | 5/10/20 bar yön-duyarlı MFE/MAE, XU100 excess return, backfill/report workflow | Yeterli saha örneği birikmesi |

- [x] Canonical bar ve snapshot kimliği
- [x] Feature registry ve snapshot-aware cache
- [x] TECHNICAL ailesindeki yedi legacy ekranın canonical scanner karşılığı
- [x] BIST seans çıpalı kapanışlar ve watermark catch-up
- [x] Event + Telegram outbox atomik PostgreSQL adapter'ı
- [x] Tek bot / çok topic yönlendirme sözleşmesi
- [x] Canonical `borsapy` veri sağlayıcı adapter'ı
- [x] İlk legacy/new shadow karşılaştırma sözleşmesi
- [x] Merkezi Telegram publisher ve listener
- [x] `/tara SYMBOL --force` için kiralamalı PostgreSQL iş kuyruğu ve worker
- [x] KAP bildirimlerini çoklu BIST sembolüyle ilişkilendiren canonical haber akışı
- [x] SIGNAL + TECHNICAL + MA için strict, yön-çatışması görünür confluence raporu
- [x] Kalıcı host öncesi GitHub Actions tabanlı kontrollü Telegram live pulse
- [x] `signal.macd_positive_cross` dikey dilimi
- [x] `signal.smi_macd_positive` (`S-M-1`) ve MA200/hacim onaylı
      `signal.smi_macd_positive_volume_confirmed` (`S-M-V-1`) dikey dilimleri
- [x] `signal.rsi_momentum_volume` (`R-V-1`) ve
      `signal.rsi_macd_volume` (`R-M-V-1`) dikey dilimleri
- [x] `signal.smi_macd_early` (`S-M-2`) ve
      `signal.smi_macd_full` (`S-M-V-2`) dikey dilimleri
- [x] `signal.sma_macd_volume` (`A-M-V-1`) ve
      `signal.ema_trend_volume` (`E-V-1`) dikey dilimleri
- [x] `ma.near_zone` state makinesi ve persistence dilimi
- [x] Wilder ATR'nin kimlikli ortak feature ve bağımlılık cache'i olarak ayrıştırılması
- [x] XIST tatil takvimi + watermark/catch-up worker
- [x] BIST Tüm (XUTUM) kaynaklı, güvenlik frenli `BIST_ALL` universe eşitlemesi
- [x] Yön-duyarlı MA Research seviye üreticisi ve günlük feature-store yenilemesi
- [x] `taramabot` içindeki dokuz legacy sinyal kodunun yeni scanner kataloğuna taşınması
- [x] `/analiz`, `/rapor` ve `/temel` için canonical uygulama servisi, BIST kamu
      finansalları + yfinance fallback ve transactional outbox
- [x] `/rapor` için deterministik kimlikli 24 bölümlü PDF ve Telegram
      `sendDocument` teslimatı
- [x] OHLCV ingestion için borsapy → yfinance fallback zinciri
- [x] `/grafik` için kaynak üreticiyle uyumlu geçiş adapter'ı
- [x] Genel piyasa haberleri ve ekonomik takvimin kaynak önceliği, bootstrap ve
      topic ayrımıyla taşınması
- [ ] Kaynak repolarda bulunmayan aracı kurum PDF/bülten sağlayıcısının ayrı
      entegrasyon olarak eklenmesi
- [ ] Tüm aileleri kapsayan shadow hattında MA Research parity ve yeterli saha örneği
- [x] KARAR v6.4.5 ailesinin canonical scanner ve gerçek legacy shadow adapteri
      olarak taşınması
- [ ] Compatibility katmanındaki araştırma, grafik ve genel haber kodunun ayrıştırılması
- [x] Sonuç/backfill ölçümü
- [ ] Corporate action veri akışı

Bu yazılım yatırım tavsiyesi veya otomatik emir sistemi değildir.
