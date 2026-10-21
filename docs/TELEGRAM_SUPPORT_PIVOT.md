# GitHub taraması ve destek/direnç gönderimi

## Normal 18 tarama

Otomatik gün içi yol **ATC automatic latest candle snapshots** workflow'udur.
Sekiz zaman diliminde (`15m`, `30m`, `45m`, `1h`, `2h`, `4h`, `1d`, `1wk`) sabit
630 hisseyi tarar. Son gerçek açık mum varsa o an kapanmış gibi yalnız
bellekte hesaplar; sonuç **CANLI / TEYİTSİZ**'dir. Gönderim, zaman diliminin
mevcut konusuna yapılır. Nominal saatler, teslim makbuzuna göre atlama ve
GitHub gecikmeleri [otomatik zamanlama kılavuzundadır](ATC_AUTOMATIC_SCHEDULE.md).
Haftalık ayrı gerçek haftalık kaynak mumundan hesaplanır.

Teyitli kapanış taraması ayrıca korunur: GitHub → Actions → **ATC six
timeframe real scan in FREE isolated PostgreSQL runner** → Run workflow →
main → scope=all. Bu manuel seçim sekiz zaman dilimini, haftalık dahil,
gerçek kapanmış mumlarla tarar. Bu eski yol yalnız manuel tanılama içindir;
otomatik tetiklemesi kaldırılmıştır. Otomatik haftalık ve Kesişim, güncel RAM
iş akışındadır.
`due` seçimi için hiç vadesi gelen dönem yoksa gerçek işler `skipped`
olabilir; yeşil planlayıcı mesajın gruba ulaştığı anlamına gelmez.

İki yol da eski Neon kotasına veya E diskinin bağlı olmasına ihtiyaç duymaz.
Teyitli yol geçici GitHub PostgreSQL, canlı yol yalnız bellek kullanır.
Sağlayıcı/kapsam kontrolleri yayını durdurabilir; eksik hisseye fiyat veya
sinyal uydurulmaz.

## Destek, direnç ve klasik pivot

Günlük otomatik yayın **ATC 630 morning support resistance and pivot report**
ile hafta içi **08:35 Türkiye saati**'nde hazırlanır. Önceki gerçek kapanmış
işlem seansı temel alınır. Her zaman dilimi için yeniden hesaplanan bir
destek/direnç yayını değildir. İşin başlaması ve veri indirme süresi nedeniyle
08:35 kesin Telegram teslim saati sayılmaz.

Actions → **ATC manual support resistance and pivot report** → Run workflow:

1. `delivery=preview`, `prepared_run_id` boş: 630 hisseyi indirip dosyaları
   hazırlar, Telegram'a mesaj göndermez. Tamamlanan çalışmanın Artifacts
   bölümünden `atc-support-pivot-report` dosyasını indirerek önizlemeye bakın.
2. Sonuç uygunsa aynı workflow'u `delivery=publish` ile çalıştırın.
   `prepared_run_id` alanına önizlemenin Actions çalıştırma numarasını girin.
   Aynı dosyalar doğrulanır; fiyatlar yeniden indirilmez veya değiştirilmez.
3. `prepared_run_id` boş bırakılan publish çalışması yeni rapor hazırlar ve
   aynı çalışmada gönderir. Yayın yalnız `main` dalından yapılabilir.

Gönderim mevcut **Raporlar (8)** konusuna yöntem açıklamalı kısa metin,
**630 hissenin tamamını içeren 32 alfabetik görsel** ve tam CSV'dir.
Her sayfada en fazla 20 hisse, son sayfada 10 hisse yer alır. Kaynak eksikliği,
işlem durması veya düz seans durumları hisseyi görselden silmez; durum etiketi
ve geçerli olmayan alanda çizgi gösterilir. Yeni konu oluşturulmaz. Başarı ancak
32 sayfanın ve metin/CSV'nin tamamı için Telegram mesaj kimlikleri
alındığında `delivery.json` ile kaydedilir. Aynı dosyadan tekrar gönderimde
kaydı bulunan parçalar tekrarlanmaz; farklı Actions çalışmaları için kalıcı
grup-geneli tekilleştirme iddiası yoktur.

- **Ana referans merdiveni:** Önceki kapanmış seansın yüksek/düşük/kapanış
  (H/L/C) değerlerinden geleneksel pivot yöntemiyle **P, S1/S2/S3 ve
  R1/R2/R3** hesaplanır. Böylece uygun veri olduğunda üç destek ve üç direnç
  gösterilir. Bunlar aracı kurum ekranlarındaki gibi matematiksel referans
  seviyeleridir; geçmişte mutlaka test edilmiş noktalar değildir. Pivotun
  çevresindedir; hepsinin son fiyatın doğru tarafında olduğu varsayılmaz.
  Düz seansta (H=L=C) çakışan seviyeler ayrıca işaretlenir. Geçersiz OHLC,
  sıfır/negatif veya sonsuz sonuç üreten alan boş ve gerekçeli bırakılır;
  mutlak değer alma, fiyatı kırpma veya değer uydurma yapılmaz.
- **Ayrı yapısal destek/direnç:** Son 120 kapalı günlük mum; üç sol ve üç
  kapanmış sağ mumla teyitli dip/tepeler; uygun tarafta en yakın en fazla üç
  destek ve üç direnç. Sıfır–üç seviye bulunabilir. Kısa geçmiş ayrı
  gösterilir, en az yedi kapalı mum gerekir. Seviyeler arası %1 ayrım
  referans fiyata göredir; başarı ihtimali değildir. Yapısal sütunun boş
  olması ana pivot merdiveninin veya hissenin listeden silindiği anlamına
  gelmez.

Görseldeki ana tablo **Traditional** yöntemidir; TradingView'in ayrı isimli
**Classic** yönteminin S3/R3 formülüyle karıştırılmaz. H önceki seansın
yükseği, L düşüğü, K kapanışı olmak üzere:

```text
P = (H + L + K) / 3
S1 = 2P − H       R1 = 2P − L
S2 = P − (H−L)    R2 = P + (H−L)
S3 = L − 2(H−P)   R3 = H + 2(P−L)
```

Formül kaynağı: [TradingView Pivot Points Standard, Traditional](https://www.tradingview.com/support/solutions/43000521824-pivot-points-standard/).
Yapısal yöntem ayrıca CSV'de tutulur; kapanışın altındaki teyitli dipler
destek, üstündeki teyitli tepeler dirençtir. Aynı tarafta seçilen seviyeler
arasında kapanışın %1'inden fazla fark bulunur. Bunlar farklı yöntemlerdir;
tek bir seviyeyi iki yöntem de bulmuş gibi gösterilmez.
- Kaynaklar aynı hissenin içinde birleştirilmez. Gözlem kesimi, sağlayıcı,
  fiyat bazı, snapshot ve pivot teyit zamanları dosyada korunur.
- Önceki seans kapanış kapsamı %90'ın altındaysa gönderim yapılmaz. Eksik
  seviyeler boş gösterilir; %90 kaynak kapsamı tüm hisselerin aynı miktarda
  geçmişi, geçerli bir pivot merdiveni veya üçer yapısal seviyesi olduğu
  garantisi değildir.

Bu yayın mevcut Stop/TP planını değiştirmez. ATR bölgesi/dönüş hafızası
araştırma adayı ve geçmişe göre kalibre edilmiş Stop/TP etkinleştirilmez.
GitHub'ın sabit 630 izleme listesi E'nin 631 üyeli araştırma evrenine
sessizce dönüştürülmez. Ayrıntılı otomatik saat tablosu ve manuel deneme
adımları [ATC otomatik zamanlama kılavuzundadır](ATC_AUTOMATIC_SCHEDULE.md).
