# ATC 630 – kapanış sonrası hızlı tarama ve veri sağlayıcı tekrar denemeleri

**Değiştirilmeyen:** Kullanıcının en son Pine kaynak dosyasındaki 1–18 tarama koşulları, kapanmış mum ilkesi, geçmiş snapshot revizyonları ve otomatik yayın güvenlik freni.

## Gerçek ilk ölçüm

GitHub Actions `38656777424` 15.10.2026 04:18 TSİ civarında başarıyla bitti:
- 630 enstrüman / 630 işlenen, 0 başarısız fiyat işleme;
- yaklaşık **86 dakika** çalışma;
- raporda `SURUM_UYUSMAZLIGI` görünen günlük 11.340 hücrenin sebebi: exporter `bist-session-v1` varsayımını kullanırken üretim `exchange-calendars-xist:<version>` hash'iyle tarıyordu. Bu PR exporter'ı gerçek runtime calendar sürümüyle hizalar.

Bu sayı, her 18 koşulun TradingView ile eşitliğini kanıtlamaz; yalnız bir tarama döngüsünün tüm hisselere ulaştığını gösterir.

## Yapılan performans düzenlemeleri

1. **Paralellik (günlük):** `scan-due --workers 8`. Her hisse kendi PostgreSQL bağlantısını ve feature cache'ini kullanır. Kuyruk, en fazla 16 gönderilmiş görevle sınırlıdır; tarama watermark'ı/döngüsü tek yönetici tarafından güncellenir. Alarm dağıtımı bu pilotta kapalıdır.
2. **Çoklu zaman dilimi artımlı OHLCV:** 5m/15m/30m/45m/1h/2h/4h ve haftalık hedef timeframe'lerde PostgreSQL'deki son kapalı mumlar okunur. Gerekli küçük örtüşme, **aynı sağlayıcının temel zaman diliminden** gelir. 45m/2h/4h ve haftalık veriler ancak tüm kaynak bucket mumları varsa oluşturulur. En az iki aynı kapanışlık örtüşme ve OHLCV eşitliği sağlanmazsa sistem otomatik **tam geçmiş indirmeye** döner; revizyonu sessizce değiştirmez. 1d önceden kullanılan artımlı yöntemini korur.
3. **Kalıcı sağlayıcı beklemesi:** `provider_retry_cooldowns` tablosu borsapy/tvDatafeed/yfinance için sembol + kaynak timeframe hatalarını tutar. İlk hata sonrası 45 dakika, tekrarlanan hatalarda üst sınırı 24 saate çıkan gecikme; başka sağlayıcı denenmeye devam eder. Başarılı kaynak tekrar bulunduğunda bekleme kaydı temizlenir. Kimlik/token dosyaya yazılmaz.
4. **Sürüm eşitliği:** Excel/CSV/ATC paneli artık `ExchangeCalendarsXist().version` ile scanner katalog hash'ini hesaplar. Eski yanlış `SURUM_UYUSMAZLIGI` sonuçları yeniden raporlanabilir; sinyal kuralları değiştirilmez.

## Yayın ve güvenlik

- `DELIVERY_MODE=disabled` varsayılanı; yeni sinyal Telegram'a basılmaz, TradingView-Python numerik parity hala ayrıca doğrulanmalı.
- `VERI_YOK`, `HESAPLANAMADI`, `KOSUL_YOK` ayrı sonuçlardır; herhangi biri ötekine dönüştürülmez.
- Veritabanındaki OHLCV arşivi ve tutarlı revizyonlar saklanır; güvenli olmayan eski bar silme yapılmaz.
- Toplam tarama süresi ve sağlayıcı hata/kota davranışı ancak yeni 8-worker GitHub pilotundan sonra gerçek olarak ölçülür.
- Artımlı 4h ve 1wk gibi türetilmiş zaman dilimleri ilk seferde yeterli geçmişi bulamazsa tam fetch yapabilir. Bu güvenlik tercihi, bir kez tamamlanan arşiv üzerinde sonraki günlerde indirme yükünü azaltmayı hedefler.

## Test kapsamı

- Python 3.11/3.12, Docker image, PostgreSQL migration-010
- Birden çok zaman diliminde kapanmış mumlardan artımlı üretim
- Sağlayıcı başarısızsa diğerine düşme, bekleme süresince gereksiz istek atmama
- Bağımsız çalışan işlerde PostgreSQL cooldown kaydının sürmesi
- İhracat motorunda gerçek XIST takvim hash'inin kullanılması

**Ek not:** Hafta içi GitHub cron işleri best-effort çalışır; belirlenen dakika garanti değildir. İzleme listesi 630 sembolü kapsasa da tüm sembollerin canlı BIST üyeliği iddiası yoktur.
