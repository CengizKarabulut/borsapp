# ATC Günlük Fiyat Verisi: Kalıcı Arşiv, Artımlı İndirme ve Saklama

## Neden?

Eski `IngestionService`, `canonical_market_bars` PostgreSQL tablosuna OHLCV geçmişini **zaten saklıyordu**, ama sonraki seanslarda hesaplama öncesi o geçmişi okumuyordu. `borsapy` ve `yfinance` bu nedenle yeniden uzun 5y dönemleri çekebiliyordu. Büyük MA araştırması 630 sembolde tarama öncesi seri çalıştığı için 1–17 koşullarını bloke ediyordu.

## Aşama 1 (bu PR)

1. **İlk tohum:** cache yoksa, mevcut `FetchRequest.bars` değerinde (ATC günlük: 600) geçmişi indir ve immutable PostgreSQL OHLCV olarak sakla.
2. **Artımlı günlük:** aynı enstrüman, **aynı kaynak, aynı fiyat düzeltme esası ve revizyon** altında son mevcut kapalı mumları PostgreSQL'den oku. Takvim yaşına göre son en az 12 mumluk örtüşme penceresini sağlayıcıdan iste; yeni teyitli mumlarla birleştir ve son 600 tam mumu yeniden hesaplamaya ver.
3. **Örtüşme / düzeltme:** son mumlar kaynakta farklılaşmış, yeterince ortak mum yok veya fiyat esası/kaynak değişmişse **tam indirmeye dön**. Aynı revizyonda eski OHLCV'yi sessizce değiştirme; mevcut snapshot store revizyon çakışmasında yeni revizyon açar.
4. **İş mantığına dokunulmaz:** tüm 18 Pine koşulu, verilen kapalı mumu ve güncel 600 mum penceresini aynı şekilde hesaplar. EMA/RSI/SMI bir önceki işlemden taşınan kaygan state ile değil, referans Pine seed ile **yeniden** türetilir. Yalnızca **1D kaynak** bu ilk artımlı sürümdedir. Intraday ve haftalık kaynaklar şimdilik mevcut güvenli tam fetch yolunda kalır.
5. **MA ayrıştırma:** `atc-630-daily.yml` içinde 630 × 112 MA tarihsel araştırmasını bekleyen adım çıkarıldı. Var olan `ma-research.yml` ayrı job olarak MA araştırmalarını sürdürebilir. Verisi hazır olmayan 18. koşulun durumu bilinmiyor kalmalıdır.
6. **Denetim:** `python scripts/atc_storage_audit.py` sadece eski satırların **sayısını** raporlar, otomatik silme yapmaz.

## Saklama / arşiv politikası

Pine `atcBars=600` varsayılanıdır. 18. tarama için uzun geçmiş ve 112 MA adayının kalitesi önemlidir. Silme için güvenli aday pencere olarak en az **1000 bar/zaman dilimi** (haftalık 800) araştırılabilir. Bunlar **sadece önerilen alt eşiklerdir**; henüz güvenli silme kararı değildir.

Snapshot referansları, şirket bölünmesi/revizyonları, plan geçmişi, yatırımcıya gönderilmiş haberler ve backtest izleri eski mumlara ihtiyaç duyabilir. Bu yüzden **yedek + referans analizi yapılmadan otomatik DELETE yoktur.**

GitHub Actions koşucuları geçicidir, kalıcı geçmiş `DATABASE_URL` PostgreSQL üzerinde saklanır. Veri sağlayıcısının fiyat serisi farklılaşırsa kaynak ve price_basis metadata ile ayrıştırılır. Bu değişiklik **sadece tekrar indirmenin maliyetini azaltmayı** hedefler; fiyat sağlayıcı kotası, eksik 630 sembolü veya 18/18 Pine parity sorunlarını otomatik çözmez.

## Sonraki aşama

- 1h/4h ve 5m/15m artımlı ingest (hem parent timeframe hem de base resampling için doğru bucketların korunması).
- Provider'dan ardışık BIST seansları doğrulama ve hacim/price adjustment çapraz denetimi.
- Kayıtlı veriye dayalı MA cache refresh dilimleme / workers.
- Sadece doğrulanmış sonuçların özel Telegram grubundaki ilgili konulara yönlendirilmesi.
