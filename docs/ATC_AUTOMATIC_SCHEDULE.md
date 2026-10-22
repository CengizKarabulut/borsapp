# ATC otomatik tarama ve günlük destek/direnç yayını

Saatler **Europe/Istanbul (Türkiye, UTC+3)** içindir. Sabit GitHub evreni
630 koddur; E'deki 631 üyeli geçmiş araştırma evreni ayrı kalır.

## Gün içi taramalar

Actions içindeki **ATC automatic latest candle snapshots** ana daldan
otomatik çalışır. Hafta içi 10:07–17:52 arasında saatin 07, 22, 37 ve 52.
dakikalarında planlayıcı kontrol edilir; ayrıca 18:30 kapanış kontrolü vardır.
Planlayıcı BIST takvimini ve gerçek seans sınırlarını kullanır. Her tetikleme
bütün zaman dilimlerini yeniden yayımlamaz; yalnız o anda vadesi gelen,
teslim edildiği doğrulanmamış en son dönemi seçer.

Tam sekiz dilimlik gönderimde bütün dilimler ayrı runner'larda paralel
çalışabilir; her dilimde veri isteği sayısı iki işçiyle sınırlı kalır.

| Zaman dilimi | Normal tam seansta nominal kontrol | Gidilecek mevcut Telegram konusu |
| --- | --- | --- |
| 15 dakika | 10:22–17:52 arasında 15 dakikada bir; son kontrol 18:30 | 15 dakika |
| 30 dakika | 10:37–17:37 arasında 30 dakikada bir; son kontrol 18:30 | 30 dakika |
| 45 dakika | 10:52, 11:37, 12:22, 13:07, 13:52, 14:37, 15:22, 16:07, 16:52, 17:37; son kontrol 18:30 | 45 dakika |
| 1 saat | 11:07–17:07 arasında saatte bir; son kontrol 18:30 | 1 saat |
| 2 saat | 12:07, 14:07, 16:07 ve 18:30 | 2 saat |
| 4 saat | 14:07 ve 18:30 | 4 saat |
| Günlük | Yalnız 18:30 günlük kapanış kontrolü | Günlük |
| Haftalık | Haftanın son gerçek işlem gününde 18:30; ayrı native haftalık RAM görüntüsü | Haftalık |

Bu aralıklar **hedef tarama sıklığıdır; bildirim teslim saati garantisi
değildir**. GitHub iş kuyruğu, 630 hissenin veri indirme/hesaplama süresi ve
sağlayıcı gecikmesi teslimi etkiler. Bir kontrol yedi dakikalık tamponla
planlanmış olsa da tarama başladığında kaynaktaki en güncel gerçek mum
okunur. GitHub yoğunlukta zamanlanmış işleri geciktirebilir veya atlayabilir;
bu durum [GitHub'ın resmi açıklamasında](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)
da belirtilir. Anlık fiyat akışı veya TradingView alarmı hızı vaat edilmez.
Tablo normal 10:00–18:00 seansı içindir. Kısa/yarım işlem seansında canlı
RAM taramasının bu sürümü desteklenmeyen seans durumunu açıkça kaydeder ve
normal saatleri o güne uydurup veri üretmez.

Windows bilgisayarı ve kullanıcı oturumu açıkken aynı `main` iş akışını
bu kontrol saatlerinde çağıran yerel yedek de kullanılabilir. Kurulum ve
sınırları [yerel tetikleme belgesinde](WINDOWS_SNAPSHOT_DISPATCH_BACKUP.md)
yer alır. Bu, hesaplama süresini kaldırmaz; GitHub cron gecikmesine karşı
ikinci tetikleme yoludur. Sabah destek/direnç raporu ayrı 08:35 görevinde kalır.

Son gerçek açık mum varsa o anki OHLCV değerleri **kapanmış gibi, yalnız
bellekte** değerlendirilir. Sonuç **CANLI / TEYİTSİZ** niteliğindedir ve mum
değiştikçe değişebilir. Kaynak açık mumu vermiyorsa bu gizlenmez; gerçek son
mumun zamanı, güncellik ve eksik veri durumu raporda korunur. Yeni mum, fiyat
ve hacim uydurulmaz; bu deneme geçmiş teyitli veri tabanına veya Stop/TP
kalibrasyonuna yazılmaz. Her kodun bütün taramalarda eşleşmesi beklenmez;
eşleşmeyen/bilinmeyen durumlar da tam CSV/JSON'da yer alır.

## Aynı dönem yeniden gönderilir mi?

Her zaman diliminde son başarılı teslimin küçük makbuzu Actions artifact'i
olarak saklanır. Bir dönem ancak bütün Telegram parçaları için gerçek mesaj
kimlikleri alınırsa tamamlandı sayılır. Sonraki planlayıcı bu makbuzları
okuyup tamamlanmış dönemi atlar. Başarısız veya yalnız önizleme çalışması
teslim edildi kaydı oluşturmaz. Makbuzlar 14 gün, rapor dosyaları iki gün
saklanır; bu düzen kalıcı bir piyasa verisi arşivi değildir.
İlk kurulumda henüz makbuz bulunmuyorsa önceki seansın en son dönemi bir
defalık yakalanabilir. Bu, eski açık mumu geriye dönük yeniden hesaplamak
değildir; çalışma anındaki son gerçek veri kullanılır ve zamanı açık kalır.

Çalışmakta olan gönderim yeni tetiklemeyle iptal edilmez. GitHub aynı
eşzamanlılık grubunda bekleyen eski çalışmanın yerine yenisini koyabilir.
Gecikmeyle kaçan eski dönemler topluca geriye dönük gönderilmez; planlayıcı
en son uygun dönemi hesaplar ve kaçırılan dönem sayısını kaydeder. Böylece
eski uyarılardan bir bildirim kuyruğu oluşmaz. Seçilen dönem, gecikme ve
gerçek veri kapsamı Actions çalışma özetinde ve `scheduled-slot.json` içinde
incelenebilir. Takvim zamanı ile sağlayıcının gerçek mum zamanı farklı
alanlardır.

45 dakikalık gerçek kaynak mumları TradingView'in **09:45, 10:30, …,
17:15, 18:00** diziliminden doğrudan okunur; 15 dakikalık seyrek işlemlerden
eksik mum tamamlanmaz. Yukarıdaki saatler bu mumların zaman etiketi değildir.
18:00 kaynak mumunun nominal bitişi 18:45 olarak korunur; bu, son işlemin
18:45'te yapıldığı veya mumun kaynaktan teyit edildiği iddiası değildir.
Bilinen geçmiş yarım seanslar ayrıca tarihlenir. Resmî işlem durmasında
son gerçek geçmiş mum hesaplanabilir; güncel sinyal veya kesişim oyu sayılmaz.

2 ve 4 saatlik taramalar da doğrudan gerçek `120` / `240` dakika
kaynağını kullanır. Kaynak gridi 09:00'dan başlar; 17:00 mumunun nominal
bitişi sırasıyla 19:00 / 21:00 olarak korunur. Bu saatler borsanın o saate
kadar işlem yaptığı anlamına gelmez. Seyrek saatlik mumlar birleştirilmez,
eksik fiyat/hacim üretilmez. Geçmiş yarım seansların kaynak gridi ayrıca
gerçek takvim ve korunmuş 09:30 etiketleriyle kontrol edilir.

15 dakika, 30 dakika ve saatlik taramalar da gerçek kaynak mumlarını
doğrudan kullanır. Sabah ve kapanış müzayedesi mumları korunur; gerçek
18:00 mumu varsa son fiyat ve hacim bu mumdan gelir. Müzayede mumu
gelmeyen hissede yalnız gerçek normal seans kapanışı açık durum etiketiyle
korunur. Fiyat, hacim veya müzayede mumu üretilmez.

Haftalık OHLCV de kaynağın gerçek `1W` mumundan okunur. Kaynak zaman etiketi
tatil haftasında pazartesi veya başka bir gün olabilir; değiştirilmez ve
borsanın gerçek açılış zamanı olarak yorumlanmaz. Nominal yedi günlük bitiş,
teyitli borsa kapanışı değildir.
Haftalık uygunluk aynı takvim haftasına aittir; son işlemin kaç saniye önce
yapıldığını göstermez. Bu tarama da **CANLI / TEYİTSİZ** olarak gönderilir.

## BIST LONG tarama ve kesişim görselleri

Her zaman diliminin kendi konusuna iki ayrı grup hazırlanabilir:
normal **LONG** ve **aynı zaman diliminde tarama kesişimi LONG**.
BIST SHORT bildirimleri tüm hisseler için kapalıdır. Normal grupta en az bir,
aynı-dilim kesişiminde en az iki **farklı tarama kimliği** aynı yönde
eşleşmelidir. İkinci bir zaman diliminin sinyali beklenmez. Düşüş hesapları
ve iki yönlü tarama kanıtları tam CSV/JSON'da korunur; bildirim yönü hesabı değiştirmez.

Her grupta **en çok 20 hisse** vardır. Önce eşleşen farklı tarama sayısı,
eşitlikte hisse kodu sıralaması kullanılır. Bu sayım başarı/getiri puanı
değildir. 1–19 hisse varsa da görsel gelir; boş grup için boş görsel üretilmez.
Gösterilen/toplam hisse sayısı ve CSV'de kalan sayı açıkça yazılır.
630 hissenin tüm 18 tarama sonucu CSV/JSON'da korunur. Her görselin kendi
teslim kimliği doğrulanmadan dönem tamamlandı sayılmaz.

Otomatik tarama grubunun ardından, mevcut **Kesişim** konusuna kısa metin,
**LONG** görseli ve tam CSV gönderilir. Bu ayrı raporda da en fazla 20 LONG
hisse gösterilir; düşüş yönü dahil tüm uygun hisseler CSV'de kalır.
Sıra önce zaman dilimi sayısı, sonra farklı tarama sayısı ve hisse kodudur.
Kesişim yoksa bunu belirten metin ve boş sonuç CSV'si gelir.

Aynı yönde en az iki farklı tarama bulunan en az iki zaman dilimi gerekir.
Mum kapanış saatlerinin eşit olması gerekmez. Her dilimin son teslim edilmiş,
aynı gerçek işlem seansına ait durumu kullanılır; gözlem yaşı dilim süresi
+ 30 dakikayı aşamaz; bu yaş gönderim başlamadan önce yeniden kontrol edilir.
Kaynağı eski, hatalı veya işlem sırası kapalı hisseler
güncel oy vermez; eksik zaman dilimleri metinde görünür. Açık mum sonucu
**CANLI / TEYİTSİZ** olarak kalır. Farklı planların Stop/TP seviyeleri
birleştirilmez. Aynı kaynak paketleri tekrar görülürse tamamlanmış teslim
makbuzu ile yinelenen gönderim atlanır.

Gün içindeki eski sıkı kapanış taraması ile saatlik günlük önizlemenin cron
tetiklemeleri kaldırılmıştır. Aynı gün içi yayını üç ayrı workflow yapmaz.
Eski **ATC six timeframe real scan in FREE isolated PostgreSQL runner**
ve diğer tek seferlik tarama/kurtarma workflow girişleri kaldırıldı.
Otomatik sekiz dilim ve Kesişim aynı güncel RAM iş akışından gelir;
bu sonuçların niteliği teyitli kapanış olarak değiştirilmez.

## Destek, direnç ve Traditional pivot

**ATC 630 morning support resistance and pivot report**, hafta içi
**08:35**'te hazırlanır ve mevcut **Raporlar** konusuna gönderilir. BIST
tatil/hafta sonu aralığında önceki gerçek işlem seansının kapanışı kullanılır.
Bu günlük rapor, sekiz zaman diliminin tarama sıklığıyla değişmez.

- CSV/JSON ve **32 alfabetik görsel 630 kodun tamamını** içerir. Her görselde
  en fazla 20 hisse, son sayfada 10 hisse vardır. Kaynağı bulunamayan veya
  işlem sırası kapalı hisse de durum etiketiyle görselde kalır.
- Ana merdiven önceki kapanmış günlük mumun yüksek/düşük/kapanışından
  hesaplanan **geleneksel (Traditional) P, S1/S2/S3 ve R1/R2/R3** seviyeleridir. Böylece veri
  uygunsa her hissede üç destek ve üç direnç referansı bulunur. Bunlar
  pivotun çevresindeki matematiksel seviyelerdir; son fiyatın mutlaka
  tamamının arasında olduğu veya tüm seviyelerin ayrı olduğu söylenmez.
  Yüksek=düşük=kapanış olan düz mumda çakışan seviyeler ayrıca belirtilir.
  Sıfır, negatif veya sonsuz sonuç üreten alan boş ve gerekçeli bırakılır;
  geçerli diğer alanlar korunur. Fiyat uydurulmaz veya mutlak değer alınmaz.
- Yapısal destek/direnç ayrıca korunur: Son 120 kapanmış günlük mumdaki üç
  sol/üç sağ kapanmış mumla teyitli dönüş noktalarıdır. Fiyata göre uygun
  tarafta en fazla üçer seviye yazılır. Bu ayrı yöntemde her iki tarafta
  sıfır–üç seviye bulunabilir; boş alan eksik hisse demek değildir.
  Yeni/kısa geçmişli hisseler ayrıca işaretlenir; en az yedi kapanmış mum
  gerekir.
- Kaynak bulunamayan kod rapordan silinmez; durumu ve boş değerleri
  korunur. Önceki seansın güncel kaynak kapsamı %90'ın altındaysa hiçbir
  parça yayımlanmaz. Bu eşik, 630 hissenin tamamında mutlaka aynı miktarda
  geçmiş, geçerli bir klasik paket veya üçer yapısal destek/direnç olduğu
  garantisi değildir.

Bu seviyeler referanstır; emir veya başarı olasılığı değildir. Kalibre
edilmiş Stop/TP araştırması, günlük destek/direnç raporundan ayrıdır.

## İstenildiğinde elle deneme

1. GitHub → Actions → **ATC automatic latest candle snapshots** →
   **Run workflow** → `main` seçin.
2. `scope=all`, `delivery=preview`: desteklenen sekiz canlı zaman dilimi
   dosya hazırlar, Telegram'a mesaj göndermez. Artifacts ve çalışma
   özetinden gerçek veri zamanlarını kontrol edin.
3. Yeni bir manuel gönderim için `scope=all`, `delivery=publish` seçin.
   Kaynak/kapsam kontrolleri geçerse mevcut konulara gönderir. Zorunlu
   manuel deneme otomatik zamanlama dönemi teslim edilmiş gibi işaretlenmez.
4. Yalnız güncel vadesi gelen dönemleri denemek için `scope=due` kullanın.
   Hiç dönem kalmadıysa gerçek taramalar `skipped` olabilir; bu normaldir.

Destek/direnç için ayrı **ATC manual support resistance and pivot report**
workflow'u korunur. `delivery=preview` dosyayı hazırlar; aynı dosyayı
göndermek için başarılı önizleme çalıştırma numarasını `prepared_run_id`
alanına yazıp `delivery=publish` çalıştırın. Güncel önceki seans tarihi ve
dosya/uygulama kimlikleri değişmişse eski önizleme gönderilmez.
