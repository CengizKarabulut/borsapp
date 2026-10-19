# Geçmiş veri eksikleri ve bağımsız araştırma aralıkları

19 Ekim 2026 incelemesi, önceki 604 işlik araştırma kaydındaki istisnaları
ayrı nedenlere ayırdı. Bunlar tamamlanmış veya kabul edilmiş profil sayıları
değildir. Araştırmanın ilerleyen kayıtları bu anlık durumun yerini alabilir.

| Önceki kaydın durumu | İş sayısı | İnceleme sonucu |
| --- | ---: | --- |
| Araştırma sonucu üreten | 573 | Fiyat düzeltme temeli ayrıca doğrulanmalı. |
| Saatlik boşluk nedeniyle 4 saatlik hesap engellenen | 18 | Gözlenen ayrı aralıklar incelendi; eksik saat üretilmedi. |
| Yetersiz kapalı mum | 12 | Dokuz yeni arzın gerçek işlem yaşıyla uyumlu. |
| Disk hatası | 1 | CWENE saatlik işinin yeniden denemesi sonuç üretti. |

Disk yeniden bağlandıktan sonraki 606 işlik kayıtta 576 araştırma sonucu,
aynı 18 boşluk ve 12 kısa geçmiş durumu bulunuyordu; CWENE saatlik `OSError`
kalmamıştı. Bu durum, fiyat serisinin ekonomik temelini doğrulamaz.

## Gerçekten henüz oluşmamış geçmiş

Dokuz hissenin arşivdeki ilk günlük **ve** saatlik tarihleri, Borsa İstanbul'un
KAP'ta veya kendi sitesinde ilan ettiği ilk işlem tarihiyle aynı. Bu nedenle
aşağıdaki yetersizlikler için ilk işlemden önce var olmayan mumları indirmek
mümkün değil. Şirketin kuruluş tarihi, payın borsada ilk işlem tarihi değildir.

| Kod | Resmî ilk işlem / arşiv başlangıcı | Günlük kapalı mum | Haftalık kapalı mum | Asgari 60 mumun altında kalan |
| --- | --- | ---: | ---: | --- |
| [AAGYO](https://www.kap.org.tr/tr/Bildirim/1589742) | 09.04.2026 | 128 | 27 | Haftalık |
| [AKHAN](https://kap.org.tr/tr/Bildirim/1553251) | 06.02.2026 | 171 | 36 | Haftalık |
| [ALBTN](https://www.kap.org.tr/tr/Bildirim/1638066) | 29.07.2026 | 56 | 11 | Günlük, haftalık |
| [ARFYE](https://www.kap.org.tr/tr/Bildirim/1532587) | 05.01.2026 | 195 | 40 | Haftalık |
| [ATATR](https://www.kap.org.tr/tr/Bildirim/1558180) | 19.02.2026 | 162 | 34 | Haftalık |
| [BESTE](https://kap.org.tr/tr/Bildirim/1555603) | 11.02.2026 | 168 | 35 | Haftalık |
| [BETAE](https://kap.org.tr/tr/Bildirim/1622197) | 01.07.2026 | 75 | 15 | Haftalık |
| [BKRGY](https://borsaistanbul.com/duyuru/15582/borsa-istanbulda-gong-bakirci-gyo-icin-caldi) | 02.09.2026 | 31 | 6 | Günlük, haftalık |
| [CITAS](https://www.kap.org.tr/tr/Bildirim/1649391) | 18.08.2026 | 43 | 8 | Günlük, haftalık |

Sayılar araştırmada kullanılan 14–15 Ekim tarihli yakalamalara aittir; güncel
verilerde yeni mumlar birikmiş olabilir. Asgari 60 kapalı mum eşiği düşürülmez.
Bu eşik tek başına her taramanın ısınmasının veya kalibrasyon için yeterli
bağımsız sinyalin oluştuğu anlamına da gelmez. Uygun bağımsız zaman dilimleri
çalışabilir; eksik olan zaman dilimi yeni gerçek mumlar geldikçe yeniden değerlendirilir.

Özellikle CITAS, Çitlekçi Mağazacılık Gıda A.Ş.'dir ve 18 Ağustos 2026'da
işleme başlamıştır. 43 günlük seriyi sırf kısa olduğu için sağlayıcının eski
bir hisseye ait veriyi kaybetmesi şeklinde yorumlamak doğru değildir.

## Saatlik boşlukta bütün geçmişi kaybetmeden araştırma

18 engelin tamamı, doğrulanmamış saatlik boşluktan kaynaklanıyordu. Bazıları
tek eski tarihe aittir; ALVES, ATEKS ve BARMA'nın engelleri yakalamanın yapıldığı
15 Ekim gününü de içerir. Az işlem, tek fiyat, durdurma veya kaynaktan eksik
geliş aynı sonuç gibi görünebilir. Eksik saate önceki kapanışı veya sıfır hacmi
yazmak, gözlenmemiş bir mumu gözlenmiş veri haline getirmez.

`scripts/atc_verified_segments.py` bu durum için bağımsız bir araştırma yardımcısıdır:

1. Tamamen eksik günler dahil, doğrulanmamış her sınırı açıkça kaydeder.
2. Sınırın önündeki ve arkasındaki gözlemleri ayrı aralıklara böler; araları birleştirmez.
3. Her aralığı kendi veri doğrulamasından ve aynı en az 60 kapalı mum eşiğinden geçirir.
4. Her aralıkta göstergelerin ve pozisyon durumunun sıfırlanmasını zorunlu sözleşme yapar.
5. Eski tam kaynağın ve seçilen satırların özetini, atlanan sınırları ve yeni türetilmiş kimliği tutar.

Eski kayıtlarda yapılan **yalnız zamansal uygunluk denemesinde** 18 hissenin
17'sinde en az bir aralık 60 kapalı mumu sağladı. Dokuzunda en son uygun aralık
en az 600 mum içeriyordu. AYES'te bu yöntemle uygun aralık bulunamadı. Örneğin
A1YEN'de 15 Ocak 2024 sonrasındaki 1.365, CEMAS'ta 14 Mayıs 2025 sonrasındaki
708 dört saatlik mum ayrı aralık olarak hazırlanabildi. Bu sayılar eksik
mumların onarıldığı veya Stop/TP'nin doğrulandığı anlamına gelmez.

## Fiyat düzeltme temeli ayrıca doğrulanmalıdır

Aynı incelemede, eski yakalama yolunun borsapy 0.11.0'a `adjust=False`
gönderirken kaynağı `splits` olarak işaretlediği saptandı. Bir sağlayıcı etiketi,
bedelsiz/bölünme düzeltmesinin doğru yapıldığını kanıtlamaz. Zamansal olarak
uygun bir aralık bu sorunu kendiliğinden çözmez. Eski kayıtlardaki 17/18 sonucu
bu nedenle ekonomik olarak doğrulanmış araştırma veya yayına hazır profil değildir.

Yardımcı, bağımsız doğrulama kanıtına ait SHA-256'yı **tam kaynak SHA-256'sına**
bağlayan açık bir `BasisVerification` olmadan hazırlama geri çağrısını dahi
çalıştırmaz. Sadece `adjustment='splits'` yazılması yeterli değildir. Doğrulama
kanıtını incelemek ve kaynak sınırlarındaki şirket işlemlerini kontrol etmek
çağıranın görevidir; yardımcı veri kaynağını kendi başına tasdik etmez.

`reset_each_segment=True` ve `carry_positions=False` koşulları olmadan da
hazırlama yapılmaz. Geri çağrı yalnız o aralığın satırlarını ve yeni bir
`reset_state=True` bağlamını alır; önceki gösterge/pozisyon durumu aktarılmaz.
Gerçek bir araştırma sürücüsü bağlanırsa aynı sıfırlamayı ayrıca uygulamalıdır.
Hazırlanan mumlar gözlem anında kapalı, sıralı, tam, doğru fiyat temelinde ve
seçilen aralığın içinde olmalıdır. Bunlar yeni bir türetilmiş kimlik alır.

Bu modül ağ isteği, tarama, geçmiş test, profil dışa aktarımı veya aktivasyon
yapmaz. Eski E araştırma sürücüsüne otomatik bağlanmış değildir. Doğru düzeltilmiş
yeni kaynaklar yeni sürümlü kimliklerle hesaplanmalıdır; eski raporların kimliği
değiştirilerek yeni veriyle doğrulanmış gibi sunulamaz.

Odaklı sözleşme testleri `tests/test_atc_verified_segments.py` dosyasındadır.

## Düzeltilmiş veriyi ayrı arşive toplama

`scripts/collect_e_adjusted_history.py` yalnız veri toplamak için hazırlanmıştır.
E'deki kurulumu kendiliğinden değiştirmez. Çalıştırılmadan önce incelenmiş yeni
`market_data.py`, `history_store.py` ve tüm kurulu kaynak kimliğinin SHA-256
değerlerinin açıkça verilmesini zorunlu tutar. Doğru kaynak yolu, SDK sürümü,
istekteki `adjust=True`, `auto_adjust=False`, `actions=False` ve dönen sürümlü
kaynak sözleşmesi yazma başlamadan kontrol edilir. Kaydedilmiş yerel veri
hesabı kullanılır; anonim girişe dönülmez.

Yeni nesneler yalnız `results/exit-research-adjusted-v2/history` altında tutulur.
Eski arşiv açılmaz, içe aktarılmaz veya yeniden etiketlenmez. Yanlışlıkla eski
nesneler yeni klasöre kopyalanırsa kaynak/adım kimliği denetimi bunu reddeder.
Varsayılan kapsam dondurulmuş 631 hisse × günlük/saatlik, tek sıralı işçidir;
başlangıç isteği 1985 ve sürüm günü 19 Ekim 2026 olarak sabitlenmiştir. Bu,
sağlayıcının bütün ömür boyu geçmişi tükettiğinin kanıtı değildir.

Toplayıcı eski araştırmayla aynı `exit-research` süreç kilidini alır. Eski süreç
önce işbirlikli olarak durmalıdır; ikinci bir paralel araştırma başlatılmaz.
`collector-contract.json` başlangıç kanıtını, `capture-summary.json` ise her
istekten önceki ve sonraki ilerlemeyi saklar. Aynı sürümle yeniden çalışınca
başarılı yeni nesneler doğrulanıp kullanılır; hatalı istekler yeniden denenir.
Yeni çıktı klasöründeki `capture.stop` dosyası istekler arasında durdurur;
üç ardışık sağlayıcı hatası da yeni istekleri keser. Disk/hesap hatalarının
gizli ayrıntıları yazdırılmaz. Bu araç tarama, kalibrasyon veya profil
aktivasyonu yapmaz; doğru istek sözleşmesi her şirket işleminin doğru işlendiği
anlamına gelmediğinden ekonomik sınır denetimi ayrıca gereklidir.

Toplama döngüsünün hesap, durdurma, yeniden kullanma, disk kaybı ve üç hata
sözleşmeleri `tests/test_collect_e_adjusted_history.py` ile çevrimdışı sınanır.
