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

## GitHub üzerinden çalıştırma

GitHub → Actions → **ATC manual live candle snapshot** → **Run workflow**:

1. Dal olarak `main` seçin. `timeframe` alanında `15m`, `30m`, `45m`, `1h`,
   `2h`, `4h` veya `1d` seçin. Bu çalışma için haftalık seçenek yoktur.
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
geneli tekilleştirme garanti edilmez.

## Yerel komutlar

```bash
python -m scripts.atc_live_snapshot --prepare --timeframe 15m --workers 2 --output-dir runtime_artifacts/live
python -m scripts.atc_live_snapshot --publish-from runtime_artifacts/live
```

Geliştirme için `--symbols ASELS,AKBNK` ile küçük bir önizleme hazırlanabilir.
Bu alt küme Telegram'a yayınlanamaz; yayın paketi sabit 630 hissenin tamamını
içermelidir. Bu komutlar E'deki geçmiş araştırmasını değiştirmez.
