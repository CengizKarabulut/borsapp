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
