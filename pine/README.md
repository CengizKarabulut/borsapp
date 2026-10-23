# TradingView: BIST grafik ve bildirim dosyaları

`ATC_BIST_18_DURUM.pine` açılan sembol ve zaman diliminin durum göstergesidir.
Pine Editor'de ayrı indikatör olarak kaydedip grafiğe ekleyin. Hisseyi veya
zaman dilimini değiştirdiğinizde 18 taramanın durumları güncellenir. Eşleşen
koşullar ve referans Giriş/Stop/TP1–2–3 ayrı tabloda gösterilir. Küçük ekranda
Mini görünümü ve dört satırlık eşleşme sayfaları kullanılır; sayfa ayarlardan
değiştirilir. Bu gösterge alarm ya da emir oluşturmaz.

`ATC_BIST_18_COKLU_ZAMAN.pine` aynı sembolü **5 dakika, 15 dakika, 1 saat,
4 saat, 1 gün ve 1 hafta** için tek matriste gösterir. Ana grafik zaman
dilimini değiştirmek bu altı sütunu değiştirmez; sembol değişince altısı da
yeni sembolü kullanır. Her sütunda 18 durum, hesaplanabilen kural sayısı,
kendi son fiyatı ve kaynak mumunun başlangıcı bulunur. `*` açık mumu
belirtir; fiyat veya saat hücresinin üzerine gelince mum sonu ve hacim
görülebilir. Eşleşme tablosunda zaman dilimi ve o kaynağın Giriş/Stop/TP
değerleri gösterilir. Tüm eşleşmeler ayarlardaki sayfalardan erişilebilir.

Bu altılı gösterge yalnız **güncel son mum gözlemidir**. Her kaynağın açık
mumu fiyat/hacim geldikçe değişebilir. Ana grafikten yüksek zamanlarda
`lookahead_on` güncel açık üst mumu getirir; düşük/eşit zamanlarda
`lookahead_off` son alt mumu seçer. İlk alt mumla karışmaz; bütün geçmiş
alt mum olaylarını veya geçmişte o anda bilinen sinyalleri yeniden oynatmaz.
Tarihsel sinyal çizimi, alarm veya backtest sonucu üretmez. 18. taramanın
geçmiş nitelendirmesi kendi kaynak bağlamındaki aynı 600 mumluk varsayılan
pencereyi kullanır; hesaplanamayan durum eşleşme yok sayılmaz. Fiyat adımına
yuvarlama sonrasında pozitif ve sıralı kalmayan referans plan gösterilmez.

Negatif durum **Düşüş/İzle** olarak korunur. 17 yalnız günlükte çalışır.
Yetersiz geçmiş, kapalı hesaplama ve nitelikli MA bulunamaması eşleşme yok
sonucundan ayrı gösterilir. Son açık mum kullanılır; koşullar değişebilir.

`ATC_TV200_LONG_REFERENCE.pine` mevcut seçilmiş 200 sembolün, onarlı 20 grup
halindeki bildirim kaynağıdır. `ATC_BIST631_LONG_REFERENCE.pine` daha geniş
631 sembollük kaynaktır. Her alarm kendi grup numarası ve 1 saatlik normal
BIST ana grafiğiyle kurulmalıdır. Negatif hesaplar kodda korunur; bildirim
kuyruğu ve son gönderim aşaması yalnız LONG kabul eder.

Kaynağı kaydetmek mevcut TradingView alarmlarının sunucu kopyasını
değiştirmez. Yeni kaynağı grafiğe ekleyip grup seçimini yaptıktan sonra ilgili
alarmın koşulunu bu yeni örnekle yeniden kaydetmek gerekir. Geniş listeli
kaynak hazır olması, bütün gruplar için alarm kurulduğu anlamına gelmez.

Seviyeler standart referanstır; geçmiş testten kalibre edilmiş değildir.
Grafik durum göstergesi BIST için hazırlanmıştır. Coin ve ABD sembollerinde
önizleme yapılabilir; piyasa eşikleri ve veri eşitliği ayrıca doğrulanmadan
bu piyasalar için alarm veya kalibrasyon hazır sayılmaz.

`ATC_GLOBAL_18_COKLU_ZAMAN.pine` açılan **ABD hissesi, coin, VİOP/vadeli,
emtia veya diğer sembolü** aynı altı zaman diliminde gösterir. Yeni bir
sembol listesi taramaz; grafikte seçtiğiniz sembolün 18 koşulunu hesaplar.
BIST göstergesi ve mevcut BIST AL alarmları ayrı dosyalarda kalır.
GLOBAL gösterge bildirim ya da emir üretmez. Negatif durum Düşüş/İzle'dir;
işlem açılabilirliği veya açığa satış yetkisi anlamına gelmez.

GLOBAL'ın BIST pay/fon/depo sertifikası ve TRY kotasyonu bağlamında mevcut
1 TRY fiyat ve 20 milyon TRY ortalama işlem tutarı filtresi korunur.
Diğer piyasalarda 10–16. koşullar pozitif fiyat ve aynı kaynağın geçerli
göreli hacmini kullanır; bu bir nakit likidite garantisi değildir. Kotasyon
para biriminde verilmiş coin hacmi ikinci kez fiyatla çarpılmaz. Vadeli
kontrat adedi nakit tutarı kabul edilmez. 17. koşulun göreli puanlaması
yalnız günlükte; 18. koşulun MA araştırması kendi kaynak geçmişindedir.
Bu piyasaların eşikleri ve Stop/TP'leri henüz piyasaya özel kalibre edilmiş
veya geriye dönük başarıyla doğrulanmış değildir.

Hacim türü ve seans bilgisi tablonun altında/ipuçlarında görülür. `n/a`
hacim metaverisi tek başına veri yok demek değildir; mevcut sonlu hacim
kullanılır. Gerçek hacim yoksa veya kaynak yalnız tik sayısı veriyorsa
hacme bağlı koşullar `HACİM YOK`/`TİK HACMİ` gösterir; eşleşme yok sonucuyla
karışmaz. Fiyat temelli 1–2 koşulu uygun geçmiş varsa devam eder. Eksik veya
gecikmiş veri için abonelik/veri kaynağı ayrıca belirleyicidir.

Grafik seansı ve sembolün fiyat düzeltmeleri korunur; 24 saatlik coin ile
ABD veya VİOP seanslarına BIST çalışma saatleri uygulanmaz. Zamanlar ilgili
borsanın saat dilimindedir. Vadeli Stop/TP fiyat kotasyonudur; kontrat puan
değeriyle çarpılmış kar/zarar veya teminat değildir. Sürekli vadeli sembolde
kontrat geçişi/geriye düzeltme geçmişi etkileyebilir; işlemde gerçek vadeyi
kontrol edin. Referans planlar fiyat adımına yuvarlandıktan sonra pozitif ve
sıralı değilse gösterilmez.

Pine metaverisi ve seans davranışı için resmi kaynaklar:
[Sembol bilgileri](https://www.tradingview.com/pine-script-docs/concepts/chart-information/),
[seanslar](https://www.tradingview.com/pine-script-docs/concepts/sessions/),
[sürekli vadeli düzeltmesi](https://www.tradingview.com/support/solutions/43000685266-how-can-i-enable-backadjustment-for-continuous-futures/).
