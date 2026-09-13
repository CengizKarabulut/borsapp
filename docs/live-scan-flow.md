# Canlı tarama akışı

Katalogda 18 tarama bulunur: taramabot kaynaklı 9 sinyal, market-telegram-suite kaynaklı 7 teknik tarama, MA seviye yakınlığı ve günlük karar paneli. tradingview-haber-botu haber işçisinde çalışır; tarama türü değildir. Etkin türlerin tamamı tarama özetine dahildir.

`scan-worker --notify` 15m, 30m, 45m, 1h, 2h, 4h, 1d ve 1wk için bağımsız zaman dilimi işçileri çalıştırır. En fazla sekiz enstrüman işi aynı anda yürür; her zaman dilimi en fazla iki iş bekletebilir. Veritabanı ve özellik önbelleği enstrüman başına ayrıdır. Aynı zaman diliminin ikinci kopyası PostgreSQL kilidiyle engellenir. Canlı işçi yalnız en son kapanmış hedef mumu işler; kaçırılan eski mumların tek tek tekrar taranmasını beklemez. Eski dönemler taranmış sayılmaz. Güncel tarama watermark'ı ilerlediğinde atlanan aralıklar otomatik yeniden oynatılmaz; geçmiş olay araştırması canlı sinyal akışından ayrı bir çalışmadır.

Sağlayıcı gecikmesi için 15 dakika pay bırakılır. Sağlayıcının son mumu hedef kapanıştan eskiyse enstrüman başarısız sayılır; eski sonuç yeni sinyal diye gönderilmez. Tam sağlayıcı hatasında watermark ilerlemez. Kısmi hatalar kapsamda görünür. Bitiş saati gerçek çalışma sonudur.

BIST işlem günlerinde 10:30–18:30 arasında her 15 dakikada SCANS konusuna her zaman dilimi için bir özet ortak outbox üzerinden girer. Sinyal olmasa da işlenen, bekleyen/erişilemeyen ve hesaplanamayan kapsam ayrı gösterilir. Her zaman diliminde en az iki aynı yönlü taramada kesişen ilk 20 hisse ve tarama adları gösterilir. Sonunda zaman dilimleri arası ilk 20 ve tüm eşleşmeleri içeren tam PDF yer alır. Uzun zaman dilimleri yeni mum kapanmadan yeni sonuç üretmez; günlük karar paneli gün sonu verisini kullanır. Haftalık mumlar XIST takvimindeki tüm günlük seansları içeren tamamlanmış haftalardan üretilir; eksik haftalar atlanır. Aylık ingestion kapsam dışıdır. Seans dışında sahte yeni sonuç oluşturulmaz.

Özet, tüm etkin taramaları içerir. Eski bireysel olay bildirimlerinin parity kısıtları korunur; özet eklenmesi geçmiş kodlarla doğrulanmamış bire bir eşitlik iddiası değildir. Özet kimliği evren/zaman dilimi/15 dakikalık dilimden oluşur; yeniden başlatma aynı mesajı tekrar kuyruğa eklemez. Veri tamamlanmasını bekleyen özet, tamamlandı diye sunulmaz. 15 dakika mesaj periyodudur; tüm evrenin hesap süresi sağlayıcı ve laptop performansına bağlıdır ve kapsam sayılarıyla görünür.

Laptop açık, uyanık ve internete bağlı olmalıdır. Otomatik oturum açılış görevi veya manuel `Start-ScheduledTask -TaskName "Borsapp Local"` aynı Docker kurulumunu başlatır.

Canlı tur için 12 dakikalık yeni iş başlatma sınırı vardır. Süre dolduğunda başlamamış hisseler hata/eksik kapsam olarak kaydedilir; sonraki tur bu noktadan dönen hisse sırasıyla başlar. Halihazırda çalışan sağlayıcı çağrısının bitmesi ayrıca beklenir.

MA araştırma döngüsü 1h, 4h, 1d ve 1wk seviyelerini yeniler. Canlı tarama 420 mum ister; bu, 377 periyotlu MA ailesini de kapsar. Birinci sağlayıcının geçmişi yetersizse ikinci sağlayıcı denenir; farklı kaynakların mumları birleştirilmez. Her ikisi de kısa geçmiş veriyorsa uzun olan tek kaynak korunur ve göstergelerin kendi asgari geçmiş kontrolleri çalışır.

borsapy dönem adları `1mo/3mo/...` biçimindedir ve istenen mum sayısına göre seçilir. Mumlar seans ve kapanış filtresinden sonra son N kayıtla sınırlandırılır. Yahoo saatlik veri, seansla hizalı 30 dakikalık iki tam mumdan türetilir; eksik çiftler ve kayık saatlik OHLC yeniden etiketlenmez.

İlk 20 adayının ANALİZ, GRAFİK ve RAPOR işleri yalnız 1h/4h/1d/1wk için kalıcı kuyruğa yazılır. Kısa zaman dilimleri SCANS'te kalır. Analiz/grafik aynı hisse, zaman dilimi ve kapanış için; şirket raporu aynı hisse ve kapanış günü için tekrar üretilmez. Şirket analizi günlük veri kullanır; tetikleyen tarama ayrıca etiketlenir. Manuel komutlar otomatik aday işlerinden önce alınır. Hesaplanamayan planlar tam PDF'de gerekçesiyle gösterilir. PDF üretimi ve sağlayıcı gecikmesi nedeniyle 15 dakika kesin teslim süresi değildir.

Tam PDF ayrı `scan-report-worker` tarafından üretilir. İlgili turun SCANS özetleri gönderilmeden PDF işi başlamaz. Çalışan PDF tamamlanır; bekleyen eski PDF turları `superseded` olarak saklanır ve sırada yalnız en güncel tur tutulur. Bu sayede yavaş disk/sağlayıcı nedeniyle eski PDF kuyruğu büyümez. PDF içindeki kapanışlar ilgili turun hedefleridir; üretim zamanı ayrıca gösterilir.
