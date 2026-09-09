# ADR-0008: İlk üretim tarama bildirimleri

- Durum: Kabul edildi
- Tarih: 2026-09-09
- Kapsam: technical.volume_spike, signal.macd_positive_cross

## Karar

İlk üretim bildirim kapısı yalnız 1d zaman diliminde iki olay tarayıcısı
için açılır:

- technical.volume_spike
- signal.macd_positive_cross

Diğer tarayıcılar ve zaman dilimleri shadow/store kipinde çalışmayı sürdürür.
Özellikle ma.near_zone ilk çalışmada tüm BIST için çok sayıda durum girişi
üretebileceğinden, gerçek 30 günlük shadow hacmi görülmeden bildirim moduna
alınmaz.

## Parity kanıtı

technical.volume_spike aynı canonical snapshot üzerinde
LegacyVolumeSpikeContractAdapter ile karşılaştırılır; alias ve MATCH sonucu
tests/test_shadow.py içinde doğrulanır.

signal.macd_positive_cross için hesap referansı ve legacy
cross OR rising-above koşulu ADR-0001 ile shadow sonuçlarından önce
dondurulmuştur. Kesişim, legacy-rising ve strict karşı örnekleri
tests/test_macd_scanner.py içinde yürütülebilir kanıttır. Gerçek legacy
adapter'larının çevrimdışı canonical frame üzerinde yüklenmesi PostgreSQL
entegrasyon işinde test edilir.

Katalog, bildirim açılan her scanner için status, verified_at ve adr
alanlarını zorunlu tutar. Bildirim zaman dilimi shadow kümesinin alt kümesi
olmak zorundadır.

## Trafik ve geri alma

Her iki scanner olay üretir; aynı sembol, scanner, finding, timeframe ve bar
kimliği outbox seviyesinde tekilleştirilir. İlk aşamada yalnız günlük kapanış
çalışması yayın yapar. Beklenmeyen trafik veya parity sapmasında geri alma,
iki scanner'ın notification_timeframes değerini boş listeye çevirmektir.

Confluence ağırlıklı puan değildir ve bu pilot tarafından ayrıca
yayınlanmaz; yalnız kanıt/zaman penceresi modeli korunur.
