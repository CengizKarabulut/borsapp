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

İlk taşınan dikey dilim `technical.volume_spike` scanner'ıdır. Pilot kuralları
[config/scanners.toml](config/scanners.toml), MACD referans kararı ise
[ADR-0001](docs/adr/0001-macd-reference-implementation.md) içindedir.

## Güncel göç durumu

- [x] Canonical bar ve snapshot kimliği
- [x] Feature registry ve snapshot-aware cache
- [x] İlk scanner: `technical.volume_spike`
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
- [x] XIST tatil takvimi + watermark/catch-up worker
- [x] BIST Tüm (XUTUM) kaynaklı, güvenlik frenli `BIST_ALL` universe eşitlemesi
- [x] Yön-duyarlı MA Research seviye üreticisi ve günlük feature-store yenilemesi
- [x] `taramabot` içindeki dokuz legacy sinyal kodunun yeni scanner kataloğuna taşınması
- [x] `/analiz`, `/rapor`, `/temel` ve `/grafik` için kaynak üreticilerle uyumlu
      geçiş adapter'ları
- [ ] Genel piyasa haberleri, ekonomik takvim ve aracı kurum bültenlerinin parity ile taşınması

Bu yazılım yatırım tavsiyesi veya otomatik emir sistemi değildir.
