# ADR-0001: MACD referans implementasyonu

- Durum: Kabul edildi
- Tarih: 2026-09-07
- Etkilenen feature: `momentum.macd`

## Karar

Ortak MACD feature'ı `MACD(12,26,9)` için `adjust=False` recursive EMA
kullanır. EMA ilk geçerli gözlemden başlar ve feature kimliği
`tradingview_recursive_ema_v1` olur. Görünürlük warmup'ı ayrıca tanımlanır;
üretim taramalarında en az 35 kapalı bar olmadan MACD sonucu kullanılmaz.

Bu karar shadow sonuçları görülmeden verilmiştir.

## Legacy karşılaştırması

| Kaynak | Hesap | Warmup görünürlüğü |
| --- | --- | --- |
| taramabot/`indicators.py` | pandas EWM, adjust=False | ilk bardan görünür |
| technical_bot/`original_indicators.py` | `tv_ema`, adjust=False | ilk bardan görünür |
| technical_bot/`stock_dashboard.py` | pandas EWM, adjust=False | her EMA kendi periyodundan sonra görünür |
| technical_bot/`research_engine.py` | pandas EWM, adjust=False | 12/26/9 min_periods uygulanır |

Yeterli geçmiş sonrasında hesap çekirdeği aynıdır; başlangıçtaki NaN görünürlüğü
farklıdır. Bu nedenle seed ve görünürlük tek bir belirsiz “MACD” adı altında
saklanmayacaktır.

## Sinyal mantığından ayrım

`taramabot.check_macd_positive_cross_signal` yalnız gerçek kesişimi değil,
MACD sinyal çizgisinin üzerindeyken MACD'nin yükselmesini de kabul eder:

    cross OR (macd > signal AND macd > previous_macd)

İlk shadow scanner legacy parity için bu davranışı ayrı
`legacy_rising_or_cross_v1` koşulu olarak koruyacaktır. Daha sıkı yalnız-kesişim
davranışı istenirse yeni scanner sürümü ve ayrı ADR gerektirir.

## Sonuçlar

- Feature cache aynı snapshot için MACD'yi bir kez hesaplar.
- Warmup eksikliği NO_MATCH değil UNKNOWN üretir.
- Shadow raporu hesap farkı ile sinyal-koşulu farkını ayrı sütunlarda gösterir.
