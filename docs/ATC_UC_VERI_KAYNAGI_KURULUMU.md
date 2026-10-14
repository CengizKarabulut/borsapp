# ATC 630 · 3 kaynaklı fiyat verisi kurtarma planı

## Öncelik

1. **borsapy** — ücretsiz BIST OHLCV sağlayıcısı; öncelikli kaynak.
2. **tvDatafeed** (`tvdatafeed-enhanced==2.2.1`) — ancak borsapy hata verir veya yeterli mum sağlamazsa TradingView `BIST:` sembolü.
3. **yfinance** — üçüncü son seçenek; `.IS` BIST hisse simgeleri.

`FallbackMarketDataProvider(prefer_complete_history=True)` kaynaklardan gerçek tam mum geçmişini tercih eder; hiçbir zaman kaynak mumlarını tek geçmişte yapay olarak birleştirmez. Sağlayıcıların split/düzeltilmiş fiyat tabanları arasında sayı uyuşmazlığı olduğunda kaynak ve `price_basis` metadata ayrı tutulur. tvDatafeed'de ayarlama geçmişinin TradingView ile doğrulanması ayrıca gereklidir; hesaplama paritesi otomatik garanti değildir.

### Kurulum ve çalışma

GitHub-hosted Actions üzerinde `pip install --editable '.[runtime,atcdata]'` kullanılır. Ek `atcdata` opsiyoneldir; başka workflow'lar tvDatafeed olmadan da çalışabilir ve borsapy/yfinance seçenekleri kalır.

Anonim tvDatafeed erişimi ücretsiz olmakla birlikte bazı sembollerde kısıtlanabilir veya erişim engellenebilir. Kullanıcı şifresi / cookies / oturum anahtarlarını repoya koyma; giriş yapmaya zorlayan yöntem kullanma. Ulaşılmaz fiyatlar **no_data/unknown** olarak kalır.

### Her gün verileri tekrar indirmemek

630 hissenin günlük 600 teyitli mumu mevcut `canonical_market_bars` PostgreSQL tablosunda tutulur. Bir sonraki taramada:
- Arşivden aynı sağlayıcı / aynı fiyat ayarı / aynı revizyondaki 600 mum kullanılır.
- Önce **aynı sağlayıcıdan** en az 12 günlük mum yeniden talep edilir, düzeltme ve devamlılık denetlenir.
- Yeni kapalı mumlar eklenir; 600 mumluk native Pine formülleri **yeniden** hesaplanır.
- Kaynak değişmişse / fiyat düzeltmesi varsa tüm geçmiş güvenle yeniden çekilir.
- Bunlar yalnız **1d** için artımlı; intraday kanalı yeniden tasarlanmadan yanlışlıkla birleştirilmez.

### Uzun çalışmanın kurtarılması

`.github/workflows/atc-630-daily.yml` dosyası eski `atc-630-daily` concurrence grubunun **v2** grubuna geçer. Yeni workflow tanımlandıktan sonraki `push` çalışması, sadece geçmişten kalan **38641050430** ve **38649036105** işlerini Github Actions `actions:write` izniyle iptal etmeyi dener. İzin eksikliği varsa açık uyarı verir; sessizce iptal edildiğini iddia etmez.

Günlük iş akışı:
- Kalıcı PostgreSQL şemasını doğrular.
- ATC_630 evrenini BIST XUTUM ile karşılaştırarak ayrı bir hedef olarak saklar.
- 630 hisse × günlük kapanmış mum için 1–18 koşul motorunu çalıştırır. Uzun MA araştırması diğer 17 koşulu bloke etmez.
- Tarama ve başarısız/eksik hisseleri veritabanında tutar, ardından ATC CSV çıktısı üretir.
- Telegram tarama yayınını yine **kapalı** tutar; sayısal Pine/Python paritesi ve 630 tamamlanma durumu doğrulanmadan sinyal göndermek güvenli değildir.

### Kontrol noktaları

GitHub Actions > **ATC 630 daily confirmed scan** işinde şu adımların başarıyla geçtiği görülmeli:
1. `Recover legacy`: iki eski blocked iş bittiyse atlanır, devam ediyorsa iptal girişimi kayda geçer.
2. `Install ... [runtime,atcdata]`: üçüncü veri kaynağı kütüphanesi yüklenir.
3. `Seed ... 630`: hedef evren tam 630 olarak kayıtlıdır; **630 kayıt = 630 başarılı OHLCV değil**.
4. `Run 630 ...`: başarı/başarısızlık sayısı açık çıkar.
5. `Export ...`: yalnız gerçek tarama değerlendirmeleri ve açık eksik/veri yok kayıtları.

**Not:** GitHub kod/CI testleri canlı veri veya Telegram başarısının kanıtı değildir; piyasa sağlayıcılarına erişim ve hesaplama tutarlılığı ilk gerçek çalışma sonucunda doğrulanacaktır.
