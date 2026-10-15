# ATC 630 · Telegram'da sabah destek–direnç / gün içi ön izleme / kesin kapanış

GitHub Actions: `.github/workflows/atc-telegram-briefings.yml`.

Tüm bildirimler mevcut botun PostgreSQL outbox kuyruğuna eklenir ve aynı iş sonunda publisher tarafından Telegram forumunun ilgili konusuna gönderilir. Aynı gün/saat tekrar edilen workflow'larda outbox anahtarı aynı kalır, çift mesajın önüne geçilir. Bilgisayarın açık olması gerekmez.

## Plan (Türkiye saati, UTC+3)

- **08:35** hafta içi: Önceki teyitli BIST seansının fiyatlarından klasik pivot S2/S1/P/R1/R2; rapor konusuna ilk 20 en yüksek kapanış×hacim hissesi ve tüm **630** sembolün kaynak/veri durumu ile CSV'si.
- **10:45–17:45, saat başına 45 geçe** hafta içi: Günlük mumun **henüz tamamlanmamış** gerçek sağlayıcı OHLCV görüntüsüyle, "bu anda kapansaydı" varsayımıyla 18 orijinal koşul hesaplanır. Tarama konusuna **CANLI / TEYİTSİZ** özeti gönderilir. Sonuç geçici olup seans içinde kaybolabilir. Sinyaller **kalıcı teyitli tarama kayıtlarına yazılmaz** ve doğrulanmış işlem alarmı/otomatik emir olarak verilmez.
- **18:45**: Var olan `atc-630-daily.yml` kesin günlük tarama hesaplamasına başlar (artımlı PostgreSQL, 8 işçi).
- **21:15**: Teyitli kapanış matrisi 630 hisse için **>=%95 güncel kapsam** veriyorsa gün sonu 18 tarama özeti raporlar konusuna gönderilir. Tarama tamamlanmadıysa yanlış/eksik sonuç yerine bu yayın başarısız olur; logdan takip edilir.

## Hesaplama ve adlandırma

Sabah raporu **klasik (floor) pivot** aritmetiğidir: `P=(H+L+C)/3`, `S1=2P-H`, `R1=2P-L`, `S2=P-(H-L)`, `R2=P+(H-L)`; yalnızca bir önceki **teyitli D1** mumundan türetilir. Bu seviyeler manuel çizilmiş trend, hacim profili veya teyitli yapısal destek/direnç ile **özdeş değildir**; harici hedef/sinyal değildir.

Gün içi `preview` çalışma zamanı, en son teyitli günlük mum geçmişi (PostgreSQL), **aynı sağlayıcı** üzerinden alınan **gerçek ancak henüz değişebilir günlük mum** ve orijinal 18 taramanın aynı hesaplama fonksiyonlarını kullanır. Bir tek günlük ön izleme bu ilk sürümde uygulanır. 5m/15m/1h/4h zaman dilimlerinin kapanmış mum taramaları önceki zamanlayıcının ayrı sorumluluğudur; bunlarda kısmi mum ön izleme **henüz etkin değildir**. Eksik sağlayıcı verisi, uygun fiyat esası bulunamaması veya önceki gün cache'in eski olması durumunda o hisse **başarısız kapsam** olarak kaydedilir, gerçeğe aykırı eşleşme üretilmez.

Bir ön izleme turunun tamamlanması **önceki 86 dakikalık ilk 630-hisse geçmiş veri indirmesiyle aynı iş değildir**; veri sağlayıcı yanıt süresi, 630 ayrı isteğin ve 18 koşul hesaplamasının toplamıdır. İlk canlı turdan önce kesin süre söylemek doğru değildir. Aynı anda birden fazla Telegram özet işi gönderilmez; GitHub Actions `concurrency` kuyruğu korur.

## Güvenlik ve erişim

- Raporlar mevcut kayıtlı `TELEGRAM_TOPIC_REPORTS` konusuna, ön izleme mevcut `TELEGRAM_TOPIC_SCANS` konusuna yönlendirilir.
- Kesin taramalar için `notification_timeframes` parity freni *aynı kalır*. Bu yeni workflow yalnız **açıkça etiketli bilgi raporları** yayınlar, doğrulanmamış taramaları teyitli alarm saymaz.
- Telegram bot token ve PostgreSQL URL sadece Actions Secrets'tan gelir. Kullanıcı veri kaynağı şifreleri repoya yazılmaz.
- Tek seferlik deneme: GitHub Actions → **ATC Telegram intraday, morning and final reports** → Run workflow → `morning`, `preview` veya `eod`; gerçek piyasadaki gerekli veri yoksa mesaj atmak yerine işlem hata verir.
- Ücretli veri kaynağı veya kullanıcı bilgisayarı zorunlu değildir. GitHub cron başlangıç saati sağlayıcı tarafından garanti edilmez.
