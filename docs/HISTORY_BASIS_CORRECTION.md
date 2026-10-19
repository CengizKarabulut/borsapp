# Geçmiş veri ve Stop/TP düzeltmesi — 19 Ekim 2026

## Doğrulanan neden

Eski, ayrı E motorunun Borsapy 0.11.0 isteği `adjust=False` kullanıyordu.
Bu seçenek bölünme düzeltmesini geri açar; temettü için kullanılan
`auto_adjust` seçeneğinden farklıdır. Adaptör buna rağmen veriyi düzeltilmiş
diye etiketliyordu. Güncel GitHub sağlayıcısının varsayılanı zaten `adjust=True`;
negatif short hedeflerini gizleyen önceki değişiklik bu veri hatasının nedeni
değildir.

İki sınırlı gerçek yanıtta HRKET'in 18 Eylül kapanışı eski arşivde 87,999296,
doğru istekte 6,285664 bulundu: oran tam 14. Bölünme sonrası ortak fiyatlar
aynıydı. ASELS'in 728 ortak kapanışı da aynı çıktı. Dolayısıyla her hissenin
hatalı olduğunu söylemiyoruz. HRKET'in 21 Eylül geçişindeki gerçek aralık
82,299296 yerine 1,21 oldu; yanlış ölçek ATR ve hedefleri şişirebiliyordu.
[KAP bedelsiz bildirimi](https://www.kap.org.tr/tr/Bildirim/1662762).

Yeni sözleşme `adjust=True, auto_adjust=False, actions=False` kullanır. İstek
parametreleri arşive kaydedilir. Bu, her şirket işleminin bağımsız ekonomik
uzlaştırmasının tamamlandığı veya sağlayıcının bütün geçmişi verdiği iddiası
değildir. `history_exhaustion=unproven` korunur.

## Eski sonuçların durumu

Eski araştırma 611 işte durduruldu: 581 hesaplanan, 18 saatlik boşluk nedeniyle
engellenen, 12 kısa geçmiş. Disk erişimi kaynaklı CWENE saatlik hatası yeniden
denemede giderildi. Eski arşiv, raporlar ve CAL18 profil paketi değiştirilmeden
korunur. Eski 125 profil yeniden doğrulanmış sayılmaz; E ayarında kapatılır.
TradingView alarm kopyaları da kalibrasyon kapalı referans kaynağa geçirilir.

Yeni indirme ayrı `results/exit-research-adjusted-v2/history` dizinine yapılır.
631 hisse için günlük ve saatlik toplam 1262 seri istenir. Haftalık günlükten,
dört saatlik saatlikten hazırlanır. Yeni arz öncesine mum eklenmez. Zamansal
boşluklar için [ayrı dönem hazırlama sözleşmesi](HISTORY_GAPS_RESEARCH.md)
geçerlidir; eski ve yeni fiyatlar birleştirilmez, eksik saatler uydurulmaz.

## İşlem sırasında fiyat ve yüzde

TL seviyeleri her zaman gösterilir; yüzde bunlara ek bir **fiyat mesafesidir**.
Alış yönlü aynı plan örneği:

| Alan | Fiyat | Girişe uzaklık |
|---|---:|---:|
| Giriş referansı | 100 TL | — |
| Stop | 96 TL | %4 |
| TP1 | 104 TL | %4 |
| TP2 | 108 TL | %8 |
| TP3 | 112 TL | %12 |

Bu, TP3'e ulaşma ihtimalinin %12 olduğu anlamına gelmez. Ekran/metin stop ve
TP1–TP2–TP3 fiyatlarını korur; mevcut ek gösterim stop ve TP3 mesafeleridir.
100 adet örneğinde stop mesafesi 400 TL fiyat riski demektir; komisyon ve
kayma buna eklenir. Kullanıcının verdiği komisyon her yönde 7/10000 (%0,07)
olarak araştırılır. Gerçek dolum fiyatı giriş referansından farklıysa fiilî
mesafeler de farklı olur. Short planda stop girişin üzerinde, hedefler altında
olmalıdır; sıfır/negatif veya eksik hedef uygulanabilir tam plan sayılmaz.

## Destek/direnç araştırması

Mevcut 120 mum / 3 sağ teyitli pivot bağlamı korunur. Akademik incelemeden
çıkan tek yeni aday, onay anında sabitlenen ATR bölgesi ve daha sonra
tamamlanan bağımsız dönüş/kırılmaların belleğidir. Bölge puanı başarı olasılığı
değildir. Aday üretime veya Stop/TP'ye bağlanmamıştır; yeni ve bağımsız bir
doğrulama protokolü gerektirir. Birincil kaynaklar, katsayıların hipotez olduğu
ve incelenmiş test döneminin yeniden kullanılmayacağı
[araştırma notunda](SUPPORT_RESISTANCE_ZONE_RESEARCH.md) açıklanır.
