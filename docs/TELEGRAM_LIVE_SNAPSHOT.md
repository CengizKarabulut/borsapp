# Açık mumla anlık durum taraması

Bu tarama, sağlayıcıdan gerçekten gelen son mumun o andaki açılış, yüksek,
düşük, son fiyat ve hacim değerlerini kullanır. Mumun kapanmasını beklemeden,
o anda kapanmış gibi tarama formüllerini hesaplar. Sonuç **CANLI / TEYİTSİZ**
olarak işaretlenir; fiyat veya hacim değiştiğinde ve mum kapandığında sonuç da
değişebilir. Piyasa kapalıysa son gerçek kapanmış mum kullanılabilir; yeni
mum, fiyat, hacim veya eksik işlem uydurulmaz.

Bu yol, normal kapanmış mum taramasından ayrıdır. Hesaplama bellekte yapılır;
teyitli mum deposuna, tarama geçmişine, Stop/TP kalibrasyonuna veya emir
sistemine yazılmaz. Referans seviyeleri ölçülmüş başarı ihtimali ya da yeni
bir kalibrasyon sonucu anlamına gelmez. Gerçek veya sanal emir oluşturmaz.

## Otomatik çalışma

**ATC automatic latest candle snapshots** normal seanslarda vadesi gelen
`15m`, `30m`, `45m`, `1h`, `2h`, `4h`, günlük ve haftalık dönemleri kontrol eder.
Günlük yeni dönem yalnız 18:30 kapanış kontrolünde vadelidir. Saat tablosu
ve manuel toplu deneme [otomatik zamanlama kılavuzundadır](ATC_AUTOMATIC_SCHEDULE.md).
Haftalık (`1wk`) gerçek haftalık kaynak mumundan, haftanın son gerçek işlem
gününde 18:30 kontrolünde hazırlanır. Bu da CANLI / TEYİTSİZ RAM sonucudur.

Tamamlanan Telegram teslimi, metin/CSV ve üretilen her yön görselinin gerçek,
birbirinden farklı mesaj kimlikleriyle saklanır. Boş yön varsa o görsel
üretilmez; güncel BIST LONG politikasında iki ile dört parça bulunabilir.
Sonraki otomatik planlayıcı aynı dönemi atlar; başarısız/önizleme çalışması
teslim kaydını ilerletmez. Bekleyen eski dönemler topluca oynatılmaz:
gecikmede yalnız en son uygun dönem seçilir, atlanan dönem sayısı kaydedilir.
İlk kurulumda makbuz yoksa önceki seansın son dönemi bir defalık yakalanabilir;
bu, önceki seansın o andaki açık mumunu yeniden oluşturmak değildir. Her
zaman çalışma anındaki son gerçek kaynak mumu kullanılır ve tarihi görünür.

GitHub kuyruğu ve sağlayıcı gecikmesi nedeniyle hedef aralık kesin teslim
garantisi değildir. Hisselerin son gerçek veri zamanlarını ve kullanılabilir
kapsamı raporda kontrol edin. Eski saatlik günlük önizlemenin otomatik cron'u
kaldırılmıştır; aynı canlı yayını ikinci bir iş tekrarlamaz.

## GitHub üzerinden tek zaman dilimini elle çalıştırma

GitHub → Actions → **ATC manual live candle snapshot** → **Run workflow**:

1. Dal olarak `main` seçin. `timeframe` alanında `15m`, `30m`, `45m`, `1h`,
   `2h`, `4h`, `1d` veya `1wk` seçin.
2. Önce `delivery=preview` seçin; `prepared_run_id` alanını boş bırakın.
   Çalışma 630 hisselik sabit listeyi tarar ve dosyaları hazırlar. Telegram'a
   mesaj göndermez.
3. Tamamlanan çalışmanın Artifacts bölümündeki `atc-live-snapshot` paketini
   açın. Özet metni, görseli ve 630 hissenin tamamını içeren CSV/JSON'u
   inceleyin. Veri alınamayan hisseler de nedenleriyle listede kalır.
4. Aynı sonuçları göndermek için tekrar Run workflow açın. Aynı zaman
   dilimini, `delivery=publish` ve önizlemenin çalışma numarasını
   `prepared_run_id` olarak girin. Dosyalar değiştirilmeden gönderilir;
   fiyatlar yeniden indirilmez. Hazırlanan paket 30 dakikadan eskiyse yeni
   önizleme hazırlamak gerekir.
5. `prepared_run_id` boş bırakılan `publish` çalışması yeni bir paket
   hazırlar ve aynı çalışmada gönderir. Gönderim yalnız `main` dalındadır.

Önceki paket yalnız bu workflow'un başarılı, elle başlatılmış `main`
çalışmasından alınabilir. Kaynak çalışma ile gönderim aynı kod sürümünde
olmalıdır; arada kod değişirse yeni önizleme gerekir. Dosya ve uygulama
kimlikleri gönderimden önce ayrıca doğrulanır. Telegram erişim bilgileri
yalnız gönderim adımına verilir, rapor dosyalarına yazılmaz.

## Sonuçları okuma

**BIST bildirimleri yalnız LONG:** Normal tarama eşleşmeleri ve aynı zaman
diliminde en az iki farklı taramanın kesiştiği hisseler ayrı LONG gruplarıdır.
SHORT bildirimleri ve SHORT görselleri kapalıdır. Düşüş yönlü hesaplamalar
silinmez; tam CSV/JSON'da incelenebilir. Her LONG grubunda en fazla 20 hisse gösterilir. Sıra eşleşen
farklı tarama sayısı ve ardından hisse kodudur; bu bir başarı olasılığı
değildir. Gösterilen/toplam sayısı görünür, tam sonuçlar CSV'de kalır.

Yeni paket sürümü `atc-unpersisted-latest-candle-v3-bist-long-only` ve
`bist-long-only-v1` bildirim politikasıyla sabittir. Politika değiştirilmiş
paket veya eski çift yönlü paket bu yayıncıdan yeniden gönderilemez.
Önceki v2 teslim makbuzları, aynı eski dönemi yeniden göndermemek için
okunabilir; bu, eski SHORT bildirimlerini yeniden etkinleştirmez.

- **630 hissenin tamamı:** Gerçek veriyle hesaplanan, hesaplanamayan ve yetersiz
  geçmişi olan hisselerin tamamı CSV/JSON'da korunur. En az %90 kullanılabilir
  son gerçek mum kapsamı sağlanmadan Telegram yayını yapılmaz. Bu eşik her hissenin her
  kuralı için yeterli geçmiş bulunduğu anlamına gelmez; belirsiz kurallar
  ayrıca belirtilir ve eşleşme sayılmaz. JSON'da hisse başına bir kayıt,
  CSV'de her hisse için 18 taramanın satırları bulunur; bir tarama birden çok
  yönlü bulgu üretirse ek satırlar olabilir.
- **Gözlem zamanı:** Hisseler sırayla veya sınırlı paralellikle çekilir.
  Her hissenin kendi veri alma zamanı vardır; rapor bu zamanların aralığını
  gösterir. Bütün hisselerin aynı saniyedeki fotoğrafı olduğu varsayılmaz.
- **Güncel ve kullanılabilir mum:** İçinde bulunulan zaman aralığına ait mum
  sayısı ayrıca gösterilir. Sağlayıcının son mumu bir önceki aralıkta
  kalmışsa bu durum gizlenmez. Seans sırasında son gerçek kaynak mumunun
  bitişi gözlemden en fazla 30 dakika önceyse ve aynı beklenen seanstaysa
  kullanılabilir son veri sayılabilir; bu, anlık veri hakkının veya gecikmesiz
  fiyatın doğrulandığı anlamına gelmez. Daha eski veri yayının kullanılabilir
  kapsamına veya son mum sinyal özetine katılmaz.
- **Teyitsiz eşleşme:** Açık mumda görülen şart, kapanışta kaybolabilir.
  Son mum için kullanılan bu geçici hesap teyitli kapanış sinyali değildir.
- **Eksik mum:** Hisse işlem görmediyse, sağlayıcı gerçek mum göndermediyse
  veya geçmiş seri uygun değilse durum eksik kalır. Mum kapanışını beklememek
  bu tür veri eksikliğini kendiliğinden çözmez.
- **Gerçek yerel mum:** Gün içi üretim yolu her zaman diliminin doğrudan
  native kaynağını kullanır; seyrek saatlik mumlar birleştirilerek eksik
  2/4 saatlik veya45 dakikalık mum üretilmez. Sabah/kapanış müzayedesi
  mumları korunur. Nominal mum bitişi son işlem zamanı veya kapanış teyidi
  değildir. Kaynak hatalarının yalnız güvenli, önceden tanımlanmış
  doğrulama gerekçeleri `KaynakHatalari` alanına yazılır.
- **Kısa seanslar:** Güncel beklenen seans yarım günse bu sürüm açıkça
  desteklenmedi hatası verir. Geçmiş yarım günlerin gerçek OHLCV değerleri
  korunur; nominal saat ve eksik birleştirme uyarıları CSV/JSON'da görünür.
- **Hız:** GitHub çalışmasının başlaması, veri çekilmesi ve 630 hissenin
  hesaplanması dakikalar sürebilir. Bu yol her fiyat değişiminde çalışan bir
  veri akışı değildir. TradingView'deki mevcut doğrudan alarmlar ayrı çalışır.

Gönderim, seçili zaman diliminin mevcut Telegram konusuna yapılır. Yeni konu
oluşturulmaz ve eksik konu ayarında başka bir konuya düşülmez. Teslim edilen
parçaların Telegram mesaj kimlikleri `publication-receipt.json` içinde
kaydedilir. Yeşil önizleme çalışması mesaj gönderildiğini göstermez;
gönderimi bu teslim kaydı doğrular. Aynı paket ve teslim kaydıyla tekrar
denemede onaylanan parçalar atlanır. Ayrı çalışmalar arasında kalıcı grup
geneli tekilleştirme garanti edilmez. Yeni otomatik workflow'un sınırlı
süreli dönem makbuzuyla atlama düzeni, bu bağımsız manuel denemeden ayrıdır.

## Günlük destek/direnç

08:35'teki ayrı günlük rapor önceki gerçek kapalı seansın H/L/C değerlerinden
ana **P, S1/S2/S3 ve R1/R2/R3** merdivenini hesaplar. 120 kapalı mumdaki
teyitli yapısal destek/direnç ayrıca ve sıfır–üç seviye olarak korunur.
Tam630 kod CSV/JSON ve32 alfabetik görseldedir; sayfa başına en çok20 hisse vardır. Canlı zaman dilimi sonuçları
bu günlük referansı kalibre edilmiş Stop/TP veya başarı ihtimali yapmaz.
Yöntem ve deneme adımları [destek/direnç kılavuzundadır](TELEGRAM_SUPPORT_PIVOT.md).

## Yerel komutlar

```bash
python -m scripts.atc_live_snapshot --prepare --timeframe 15m --workers 2 --output-dir runtime_artifacts/live
python -m scripts.atc_live_snapshot --publish-from runtime_artifacts/live
```

Geliştirme için `--symbols ASELS,AKBNK` ile küçük bir önizleme hazırlanabilir.
Bu alt küme Telegram'a yayınlanamaz; yayın paketi sabit 630 hissenin tamamını
içermelidir. Bu komutlar E'deki geçmiş araştırmasını değiştirmez.
