# TradingView: BIST grafik ve bildirim dosyaları

`ATC_BIST_18_DURUM.pine` açılan sembol ve zaman diliminin durum göstergesidir.
Pine Editor'de ayrı indikatör olarak kaydedip grafiğe ekleyin. Hisseyi veya
zaman dilimini değiştirdiğinizde 18 taramanın durumları güncellenir. Eşleşen
koşullar ve referans Giriş/Stop/TP1–2–3 ayrı tabloda gösterilir. Küçük ekranda
Mini görünümü ve dört satırlık eşleşme sayfaları kullanılır; sayfa ayarlardan
değiştirilir. Bu gösterge alarm ya da emir oluşturmaz.

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
