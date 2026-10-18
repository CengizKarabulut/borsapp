# GitHub ve E manuel taramasının birlikte kullanımı

GitHub deposu bu projenin mevcut kaynağıdır. GitHub'ın güncel canonical tarama
motoru ile E'de geçmiş testleri doğrulanmış yerel motor farklı sürümlerdir.
Birini diğerinin `src` klasörüne topluca kopyalamak, mevcut kalibrasyonların
kaynak kimliğini bozar. Bu nedenle bu sürüm ortak destek/direnç bileşenini ve
yerel sunum köprüsünü ayrı, hash ile kayıtlı dosyalar olarak dağıtır.

## Short Stop/TP neden eksi görünebiliyordu?

Short hedefler giriş fiyatının altında sıralanır. Eski yapısal modelde giriş30,
stop47 ve risk17 olduğunda 1R/2R/3R hedefleri13/−4/−21 olur. Sıfırın altındaki
son iki değer uygulanabilir fiyat değildir. Bu sürüm, formülü değiştirmeden
bu alanları JSON'da `null`, raporda `-` ve planı **UYGULANAMAZ** gösterir.
Pozitif görünen parçalar tam ve geçerli bir plan sayılmaz. Negatif hedefin
mutlak değeri alınmaz, stop daraltılmaz, başka kuraldan hedef eklenmez.

E'nin mevcut motoru zaten bu tür tam senaryoları reddeder. E köprüsü bunu
metinde açıklar; geçerli kalibre Stop/TP1/TP2/TP3 hesabını ve en yakın bütün
plan seçimini korur. Stop sabittir; otomatik emir veya yeni stop taşıma yoktur.

Pozitif bir hedefin uzak olması tek başına hesap hatası değildir. Kalibrasyon
bulunmayan standart model son7mum yapısı ile ATR'den risk çıkarır; bu riskin
1/2/3katı hedefleri uzak olabilir. Görselde `PLAN` altında Stop mesafesi,
CSV'de ve E metninde Stop/TP3 mesafeleri giriş referansına göre yüzde olarak
gösterilir. Bunlar aynı tam planın fiyat farklarıdır; başarı olasılığı, günlük
fiyat limiti veya beklenen kazanç değildir. Seviyeler kırpılmaz; eksik veya
uygulanamaz plan için bu yüzdeler üretilmez. `Kalibre referans` ve standart
`Referans` ayrımı korunur.

## Destek ve direnç

Hesabın geçmişte başarılı olup olmadığı ayrı ölçülür. İlk16hisselik deney ve
veri sürekliliği koşulları [araştırma notunda](https://github.com/CengizKarabulut/borsapp/blob/main/docs/SUPPORT_RESISTANCE_RESEARCH.md).
Yeni aday saklanan testte iyileşmediği için mevcut120/3 ayarı korunur.

`scripts/atc_support_resistance.py`, araştırma modülünün son120mum içindeki
3sol+3sağ teyitli pivot yöntemini taşır. En çok üç destek ve üç direnç,
birbirinden referans fiyatın%1'inden fazla uzaklıkta seçilir. Açık veya henüz
bilinemeyen mum, pivotun sağ teyidi sayılamaz. Fiyata eşit seviye iki tarafa
da konulmaz. Kısa arz geçmişi ve veri kalitesi ayrı durumlarla kaydedilir.

E'de her bulgunun bu çalıştırmada arşivlenmiş, hash'i doğrulanan aynı OHLCV
görünümü kullanılır. TXT/Telegram metnine `D/R (kapanmış mum)` eklenir; JSON
ayrıca kaynak, zaman dilimi, fiyat düzeltmesi, snapshot ve teyit tarihlerini
tutar. Bu seviyeler Stop/TP profilinin yerine geçmez. Pivot olmayan tarafta
`—`, geçmiş/veri yetersizse açıklama görünür. Mevcut PDF planı değiştirilmez.

## E kurulumu ve güncelleme

Depodaki kaynak dosyalar ile E'deki dosyalar aynı içerikten kurulur:

```powershell
& 'E:\Borsapp-Manual\.venv\Scripts\python.exe' -B scripts\install_e_manual_bridge.py --verify-only
& 'E:\Borsapp-Manual\.venv\Scripts\python.exe' -B scripts\install_e_manual_bridge.py
```

Komutlar güncel repo klasöründe çalışır. Kurucu yalnız `tools` içindeki iki
Python dosyasını, bu açıklamayı ve entegrasyon kaydını kurar. Önce yerel tarama
kilitlerini alır, eski dosyaları `updates/manual-integration-*` altında yedekler
ve hata olursa eski baytları geri yükler. Kaynak motor, kişisel ayarlar,
kalibrasyon paketi, ham geçmiş ve TradingView alarmları değiştirilmez.
Kurulum sonunda `--preview` kontrolü tarama veya Telegram gönderimi yapmaz.

Normal kullanım yine **`E:\Borsapp-Manual\Tarama-Gonder.bat`** dosyasıdır.
Yalnız bu dosyayı kullanıcı çalıştırınca seçili tarama ve mevcut Telegram
teslimat akışı işler. Kurulum veya testler Telegram mesajı göndermez.

`E:\Borsapp-Manual\tools\manual-integration.json`, repo adresini, kurulan
dosyaların hashlerini, korunan motor kimliğini ve profil paketinin hashini
gösterir. Sonraki repo değişiklikleri test edilip aynı kurucuyla E'ye taşınır;
bulut ve E motorlarının bütün formülleri ya da veri kaynakları eşit kabul
edilmez. Eski CAL18 kurucusu önceki sunum dosyası hashine bağlıdır; onu tekrar
çalıştırırken yeni dosyayı sessizce eski sürüme çevirmek yerine kontrol hatası
vermesi beklenir. Geri dönüş, bu entegrasyonun kendi yedeğinden yapılır.
