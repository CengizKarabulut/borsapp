# Canlı tarama akışı

Katalogda 18 tarama bulunur: taramabot kaynaklı 9 sinyal, market-telegram-suite kaynaklı 7 teknik tarama, MA seviye yakınlığı ve günlük karar paneli. tradingview-haber-botu haber işçisinde çalışır; tarama türü değildir. Etkin türlerin tamamı tarama özetine dahildir.

`scan-worker --notify` 15m, 30m, 45m, 1h, 2h, 4h ve 1d için bağımsız zaman dilimi işçileri çalıştırır. En fazla sekiz enstrüman işi aynı anda yürür; her zaman dilimi en fazla iki iş bekletebilir. Veritabanı ve özellik önbelleği enstrüman başına ayrıdır. Aynı zaman diliminin ikinci kopyası PostgreSQL kilidiyle engellenir. Canlı işçi yalnız en son kapanmış hedef mumu işler; kaçırılan eski mumların tek tek tekrar taranmasını beklemez. Eski dönemler taranmış sayılmaz. Güncel tarama watermark'ı ilerlediğinde atlanan aralıklar otomatik yeniden oynatılmaz; geçmiş olay araştırması canlı sinyal akışından ayrı bir çalışmadır.

Sağlayıcı gecikmesi için 15 dakika pay bırakılır. Sağlayıcının son mumu hedef kapanıştan eskiyse enstrüman başarısız sayılır; eski sonuç yeni sinyal diye gönderilmez. Tam sağlayıcı hatasında watermark ilerlemez. Kısmi hatalar kapsamda görünür. Bitiş saati gerçek çalışma sonudur.

BIST işlem günlerinde 10:30–18:30 arasında her 15 dakikada SCANS konusuna her zaman dilimi için bir özet ortak outbox üzerinden girer. Sinyal olmasa da işlenen, bekleyen/erişilemeyen ve hesaplanamayan kapsam ayrı gösterilir. Her tarama için toplam eşleşme ve alfabetik ilk 10 hisse gösterilir; bu bir puan sıralaması değildir. Uzun zaman dilimleri yeni mum kapanmadan yeni sonuç üretmez; günlük karar paneli gün sonu verisini kullanır. Haftalık/aylık ingestion bu akışın kapsamı değildir. Seans dışında sahte yeni sonuç oluşturulmaz.

Özet, tüm etkin taramaları içerir. Eski bireysel olay bildirimlerinin parity kısıtları korunur; özet eklenmesi geçmiş kodlarla doğrulanmamış bire bir eşitlik iddiası değildir. Özet kimliği evren/zaman dilimi/15 dakikalık dilimden oluşur; yeniden başlatma aynı mesajı tekrar kuyruğa eklemez. Veri tamamlanmasını bekleyen özet, tamamlandı diye sunulmaz. 15 dakika mesaj periyodudur; tüm evrenin hesap süresi sağlayıcı ve laptop performansına bağlıdır ve kapsam sayılarıyla görünür.

Laptop açık, uyanık ve internete bağlı olmalıdır. Otomatik oturum açılış görevi veya manuel `Start-ScheduledTask -TaskName "Borsapp Local"` aynı Docker kurulumunu başlatır.

Canlı tur için 12 dakikalık yeni iş başlatma sınırı vardır. Süre dolduğunda başlamamış hisseler hata/eksik kapsam olarak kaydedilir; sonraki tur bu noktadan dönen hisse sırasıyla başlar. Halihazırda çalışan sağlayıcı çağrısının bitmesi ayrıca beklenir.

MA araştırma döngüsü 1h, 4h ve 1d seviyelerini yeniler. Canlı tarama 420 mum ister; bu, 377 periyotlu MA ailesini de kapsar. Birinci sağlayıcının geçmişi yetersizse ikinci sağlayıcı denenir; farklı kaynakların mumları birleştirilmez. Her ikisi de kısa geçmiş veriyorsa uzun olan tek kaynak korunur ve göstergelerin kendi asgari geçmiş kontrolleri çalışır.
