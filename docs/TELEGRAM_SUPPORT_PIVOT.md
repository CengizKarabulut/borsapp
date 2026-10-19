# GitHub taraması ve destek/direnç gönderimi

## Normal 18 tarama

GitHub → Actions → **ATC six timeframe real scan in FREE isolated PostgreSQL runner**
→ Run workflow → main → scope=all. Sekiz zaman diliminde sabit 630 hisseyi
tarar; sonuçları mevcut zaman dilimi konularına PNG ve tam CSV olarak gönderir.
`due` seçeneği yalnız yeni kapanan zaman dilimlerini seçer. Yeşil bir `due`
çalışmasında bütün gerçek tarama adımları `skipped` olabilir; bu sonuçların
yeniden tarandığı veya gruba gönderildiği anlamına gelmez.

Bu yol geçici GitHub PostgreSQL kullanır; eski Neon kotasına veya E diskinin
bağlı olmasına ihtiyaç duymaz. Gerçek sağlayıcı eksikliği varsa tam kapsam
kapısı yayını durdurabilir; eksik hisseye fiyat veya sinyal uydurulmaz.

## Destek, direnç ve klasik pivot

Actions → **ATC manual support resistance and pivot report** → Run workflow:

1. `delivery=preview`, `prepared_run_id` boş: 630 hisseyi indirip dosyaları
   hazırlar, Telegram'a mesaj göndermez. Tamamlanan çalışmanın Artifacts
   bölümünden `atc-support-pivot-report` dosyasını indirerek önizlemeye bakın.
2. Sonuç uygunsa aynı workflow'u `delivery=publish` ile çalıştırın.
   `prepared_run_id` alanına önizlemenin Actions çalıştırma numarasını girin.
   Aynı dosyalar doğrulanır; fiyatlar yeniden indirilmez veya değiştirilmez.
3. `prepared_run_id` boş bırakılan publish çalışması yeni rapor hazırlar ve
   aynı çalışmada gönderir. Yayın yalnız `main` dalından yapılabilir.

Gönderim mevcut **Raporlar (8)** konusuna bir kısa metin, bir ilk-20 görseli
ve **630 hissenin tamamını** içeren CSV'dir. Yeni konu oluşturulmaz. Görsel,
önceki kapanış × hacim sırasındaki ilk 20'yi gösterir; kalan hisseler ve eksik
veri durumları CSV/JSON'da korunur. Başarı ancak Telegram mesaj kimlikleri
alındığında `delivery.json` ile kaydedilir. Aynı dosyadan tekrar gönderimde
kaydı bulunan parçalar tekrarlanmaz; farklı Actions çalışmaları için kalıcı
grup-geneli tekilleştirme iddiası yoktur.

- **Yapısal destek/direnç:** Son 120 kapalı günlük mum; üç sol ve üç kapanmış
  sağ mumla teyitli dip/tepeler; en yakın üç destek ve üç direnç. Kısa geçmiş
  ayrı gösterilir, en az yedi kapalı mum gerekir. Seviyeler arası %1 ayrım
  referans fiyata göredir; başarı ihtimali değildir.
- **Klasik pivot:** Önceki kapanmış seansın H/L/C değerlerinden P, S1/S2,
  R1/R2. Yapısal seviyelerden ayrı sütunlarda bulunur. Matematiksel olarak
  sıfır, negatif veya sonsuz çıkan klasik paket kullanılabilir sayılmaz.
- Kaynaklar aynı hissenin içinde birleştirilmez. Gözlem kesimi, sağlayıcı,
  fiyat bazı, snapshot ve pivot teyit zamanları dosyada korunur.
- Önceki seans kapanış kapsamı %90'ın altındaysa gönderim yapılmaz. Eksik
  yapısal seviyeler boş gösterilir; %90 kaynak kapsamı tüm hisselerin aynı
  miktarda geçmişi veya destek/direnci olduğu anlamına gelmez.

Bu yayın mevcut Stop/TP planını değiştirmez. ATR bölgesi/dönüş hafızası
araştırma adayı ve geçmişe göre kalibre edilmiş Stop/TP etkinleştirilmez.
GitHub'ın sabit 630 izleme listesi E'nin 631 üyeli araştırma evrenine
sessizce dönüştürülmez. Yeni otomatik zamanlama eklenmemiştir.
