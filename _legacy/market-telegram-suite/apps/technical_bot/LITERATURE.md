# Teknik yorum motorunun literatür dayanağı

Bu dosya rapordaki yorumların neden **koşullu** yazıldığını açıklar. Amaç,
tek tek göstergeleri mekanik AL/SAT oylarına dönüştürmek değil; fiyat/trend,
ivme, volatilite ve katılımı ayrı kanıt aileleri olarak okumaktır.

## Tasarım ilkeleri

1. **Trend ana bağlamdır; osilatörler zamanlama ve ivme bağlamı sağlar.**
   Aynı ailedeki göstergeler ayrı oy gibi sayılmaz.
2. **Hacim teyittir, garanti değildir.** Fiyat hareketinin katılımını
   açıklar; kurumsal fon akışını doğrudan kanıtlamaz.
3. **Volatilite yön değildir.** ATR gibi ölçüler beklenen dalga boyunu ve
   risk ortamını anlatır.
4. **Kapanış ve geçersizlik koşulu gerekir.** Canlı mumdaki kesişim kapanışa
   kadar değişebilir.
5. **Geçmiş performans kalıcı varsayılmaz.** Veri madenciliği, kural seçimi,
   işlem maliyeti ve piyasa rejimi teknik kural sonuçlarını değiştirebilir.

## Temel kaynaklar

- J. Welles Wilder Jr. (1978), *New Concepts in Technical Trading Systems*.
  RSI, ATR, Directional Movement/ADX ve Parabolic SAR'ın özgün sistem
  bağlamı. ISBN 0894590278.
- Brock, Lakonishok & LeBaron (1992), “Simple Technical Trading Rules and
  the Stochastic Properties of Stock Returns,” *Journal of Finance* 47(5),
  1731–1764. https://doi.org/10.1111/j.1540-6261.1992.tb04681.x
- Blume, Easley & O'Hara (1994), “Market Statistics and Technical Analysis:
  The Role of Volume,” *Journal of Finance* 49(1), 153–181.
  https://doi.org/10.1111/j.1540-6261.1994.tb04424.x
- Sullivan, Timmermann & White (1999), “Data-Snooping, Technical Trading
  Rule Performance, and the Bootstrap,” *Journal of Finance* 54(5),
  1647–1691.
- Lo, Mamaysky & Wang (2000), “Foundations of Technical Analysis:
  Computational Algorithms, Statistical Inference, and Empirical
  Implementation,” *Journal of Finance* 55(4), 1705–1765.
  https://doi.org/10.1111/0022-1082.00265
- Moskowitz, Ooi & Pedersen (2012), “Time Series Momentum,” *Journal of
  Financial Economics* 104(2), 228–250.
  https://doi.org/10.1016/j.jfineco.2011.11.003
- Bajgrowicz & Scaillet (2012), “Technical Trading Revisited: False
  Discoveries, Persistence Tests, and Transaction Costs,” *Journal of
  Financial Economics* 106(3), 473–491.
  https://doi.org/10.1016/j.jfineco.2012.06.001

## Rapora yansıması

Her gösterge şeması dört alan üretir:

- **Şu an:** ölçülen değer ve ilişkiler,
- **Gündelik anlam:** teknik terimin sade karşılığı,
- **Teyit:** mevcut okumanın güçlenmesi için gereken kapanış/uyum,
- **Risk / bozulma:** okumanın zayıfladığı veya geçersiz kaldığı durum.

Bu çerçeve yatırım tavsiyesi, getiri tahmini veya otomatik işlem sistemi
değildir.
