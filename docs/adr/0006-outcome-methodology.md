# ADR-0006: Finding outcome ölçüm yöntemi

## Durum

Kabul edildi - 2026-09-08

## Karar

- Giriş fiyatı, event üreten kapalı mumun kapanışıdır.
- Ufuklar varsayılan olarak 5, 10 ve 20 kapalı bardır.
- Bearish bulgularda getiri işareti ters çevrilir; başarı yönle birlikte ölçülür.
- MFE en iyi, MAE en kötü yön-duyarlı intrabar harekettir.
- Benchmark XU100 aynı timeframe, kaynak ve fiyat bazında varsa hesaplanır.
- Benchmark veya tam ufuk yoksa ilgili değer `NULL` kalır; sıfır yazılmaz.
- Kimlik `(event_id, horizon_bars, methodology_version)` olup backfill idempotenttir.

## Sınır

Bu çıktı scanner davranışını mühendislik açısından değerlendirmek içindir. İşlem
maliyeti, kayma, vergi, hayatta kalma yanlılığı ve portföy kısıtlarını tam modellemez;
yatırım tavsiyesi veya gelecek getiri garantisi olarak sunulamaz.
