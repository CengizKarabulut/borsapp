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

    python -m unittest discover -s tests -v
    python scripts/audit_purity.py --root _legacy --output docs/migration/purity-audit.json
    python scripts/map_indicators.py --root _legacy --output docs/migration/indicator-map.json
    python scripts/build_migration_inventory.py --root _legacy --output docs/migration/file-inventory.csv

PostgreSQL geliştirme servisi:

    docker compose up -d postgres

Bu yazılım yatırım tavsiyesi veya otomatik emir sistemi değildir.
