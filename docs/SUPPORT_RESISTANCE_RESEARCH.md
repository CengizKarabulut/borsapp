# Destek/direnç: hesap doğruluğu ve geçmiş tepki ölçümü

**19 Ekim veri düzeltmesi:** Aşağıdaki 18 Ekim pilotu, eski E adaptörünün
`adjust=False` kullanarak bölünme düzeltmesini geri açtığı bir arşive dayanır.
Dosya hashleri doğrudur; ekonomik fiyat esası etiketi doğru değildir. Bu yüzden
pilotun sayısal sonuçları doğrulanmış ekonomik başarı veya bir yöntemin üstünlük
kanıtı sayılmaz. Eski veriler ve sonuçlar değiştirilmeyip denetim için korunur.
Yeni deneyler ayrı v2 arşivinden, gerçek istek parametreleri doğrulanarak yapılır.
İncelenmiş 16 hissenin test dönemi yeniden temiz saklı test kabul edilmez.
Yeni sabit aday ve birincil akademik kaynaklar
[bölge araştırması notunda](SUPPORT_RESISTANCE_ZONE_RESEARCH.md) açıklanmıştır.

Mevcut üretim hesabı 120 kapanmış mumda 3 sol + 3 sağ teyitli pivotları kullanır.
Fiyatın altında/üstünde en yakın üç farklı seviye seçilir. Sabit yüzde1 ayırma,
ikinci/üçüncü seviyeleri etkiler; yalnız en yakın seviyeyi ölçen deney bunun
ATR tabanlı ayırmadan daha iyi olduğunu gösteremez. Bu yöntem aracı kurumların
kapalı modelleriyle eşdeğer veya her hisse için en iyi kabul edilmez.

## İlk ölçüm: 18 Ekim 2026

Veri: kullanıcının arşivindeki hash doğrulanmış, 15 Ekim tarihli günlük kayıtlar.
16 hisselik önceden belirlenmiş panel: ASELS, AKBNK, THYAO, TUPRS, EREGL, BIMAS,
MGROS, KCHOL, SISE, SASA, AKSA, LOGO, MAVI, GESAN, ALFAS, HRKET. Erişilen bütün
geçmiş kullanıldı; bu panel bütün631 hisselik evreni temsil eden rastgele örneklem
değildir. Güncel evren geçmişteki kapanan/kottan çıkan şirketleri içermediği için
hayatta kalma yanlılığı da vardır.

Dokuz aday: 60/120/252 mum × 2/3/5 teyit genişliği. Bütün adaylarda ortak252mum
başlangıcı, 21mum aralıklı tarihler, ilk temas için10mum ve temas sonrasında10mum
tepki penceresi kullanılır. ATR14 ve seviye değerlendirme tarihinde sabitlenir.
Hedef, seviyeden1ATR olumlu hareket; ihlal, ters yönde0,5ATR harekettir.
Temas mumundaki olumlu uç, temastan önce oluşmuş olabileceği için başarı sayılmaz.
Aynı mumda iki sınır da görülürse sıra belirsiz tutulur. Fiyat boşluğu, süre sonu,
seviye yokluğu, temas yokluğu ve geçersiz ölçüm sınırı ayrı sayılır.

Eğitim: Ekim2022 öncesi; seçim: Ekim2022–Eylül2024; saklanan test:
Ekim2024 sonrası. Sonuç penceresi dönem sınırını aşan kayıtlar çıkarılır. Aday
seçimi yalnız seçim dönemindeki hisse başına eşit ağırlıklı ölçümden yapılır;
test sonucu aday seçimine girmez. Önce protokol, sonra seçim kaydı yazılır.

Önemli veri kontrolü: önceki kapanıştan sonraki açılışa mutlak değişimi yüzde30'u
aşan, henüz uzlaştırılmamış geçişlere rastlayan252mum geçmiş +20mum sonuç
pencereleri bütün adaylardan birlikte çıkarılır. Bu bir veri inceleme eşiğidir;
bölünme kanıtı veya otomatik fiyat düzeltmesi değildir. Gelecekteki veri kalitesi
nedeniyle yapılan bu çıkarma, canlı işlemde bilinebilen bir sinyal diye sunulmaz.
İlk deneyde810 tarih penceresi bu nedenle ayrıldı; 3.776 ortak tarih kaldı.

Saklanan testteki **kesin olumlu tepki / bütün temaslar**:

| Yöntem | Destek | Direnç |
|---|---:|---:|
| Mevcut120/3 | 59/187 = %31,6 | 57/192 = %29,7 |
| Seçim döneminde seçilen252/5 | 51/171 = %29,8 | 44/184 = %23,9 |

Belirsiz mumların tümü olumlu sayılsaydı mevcut yöntemin üst sınırları destek
için %35,3, direnç için %35,9 olurdu. Bunlar istatistiksel güven aralığı değildir.
Paneldeki yeni aday testte mevcut yöntemi geçmedi; **üretime alınmadı**. Bu sonuç
mevcut yöntemin kârlı, tesadüften üstün veya diğer bütün adaylardan iyi olduğunu
kanıtlamaz. Temas oranları ve seviyeye ATR uzaklığı farklıdır; tabloda aynı
işlemler üzerinde eşleştirilmiş bir strateji karşılaştırması yoktur.

Bu deney emir gerçekleşmesi veya net kâr simülasyonu değildir; komisyon/kayma
getirisi hesaplanmaz. Kullanıcının gerçek7/10.000 komisyonu, ayrı Stop/TP
strateji araştırmasının maliyetidir. Tepki yüzdesi yatırım getirisi gibi okunmaz.

## Yeniden çalıştırma

Güncel repo klasöründen, yeni ve boş bir çıktı yolu verilir:

```powershell
& 'E:\Borsapp-Manual\.venv\Scripts\python.exe' -B scripts\run_sr_pilot.py --root 'E:\Borsapp-Manual' --output 'C:\SR-Deney-Yeni'
& 'E:\Borsapp-Manual\.venv\Scripts\python.exe' -B scripts\audit_history_continuity.py --root 'E:\Borsapp-Manual' --output 'C:\Veri-Inceleme-Yeni'
```

İkinci komut bütün günlük arşivleri ve aktif profillerin ek saatlik kaynaklarını
inceler; orijinal satırları veya profilleri değiştirmez. Çıktılardaki kaynak
hashleri, fiyat geçişleri ve kapsam bilgileri, yeni kalibrasyon yayımlanmadan
önce şirket işlemleriyle uzlaştırılmalıdır. Özellikle kaynağın `splits` etiketi
taşıması, bölünmelerin ekonomik olarak doğru düzeltildiğini tek başına göstermez.

631 günlük kaynak dosyasının tamamı hash/şema kontrolünden geçti. Bu inceleme
eşiğinde407 seride bütün geçmiş boyunca,177 seride son600mumda,67 seride son252
mumda en az bir geçiş işaretlendi. Aktif125profilin94'ü, bütün geçmişinde böyle
bir işaret bulunan bir kaynakla eşleşiyor. Bu,94profilin hatalı olduğunu veya
test olaylarının mutlaka o geçişe rastladığını kanıtlamaz. Profil başına olay
ve fiyat düzeltmesi incelemesi yapılmadan yeni bir doğrulanmış başarı iddiası
kurulmaz. Eşik altındaki geçişler ve uzun süreli sert düşüşler de ayrıca risk
yaratabilir; işaret bulunmaması ekonomik doğrulama garantisi değildir.

Örnek: HRKET için21Eylül2026 tarihli yüzde1.300 bedelsiz sermaye artırımı
[şirketin KAP bildirimi](https://www.kap.org.tr/tr/Bildirim/1662762) ile doğrulanır.
Arşivde aynı sınırın iki yanında farklı fiyat ölçekleri bulunması ayrıca
incelenmelidir; orijinal veri sessizce bölünme katsayısıyla değiştirilmez.

Pivotların teyit ve geçmişe bilgi taşıma riskleri:
[TradingView teknik açıklaması](https://www.tradingview.com/pine-script-docs/concepts/repainting/).
Zamansal seçim ve aralık ayırma yaklaşımı:
[TimeSeriesSplit dokümantasyonu](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).
Deney bu kütüphaneyi çağırmaz; açık tarih sınırlarını kendi kodunda uygular.

Üç sonraki araştırma alanı: teyitli seviyelerde tekrar test/yaş/volüm niteliği;
ATR ile bölge birleştirmeyi ikinci/üçüncü seviyeler dahil ölçmek; farklı zaman
dilimlerinden gelen seviyelerin örtüşmesini ayrı, geleceği görmeyen bir deneyde
karşılaştırmak. Bu ilk ölçümden sonra saklanan test tekrar parametre seçimi için
kullanılmaz; sonraki adaylara yeni doğrulama planı gerekir.
