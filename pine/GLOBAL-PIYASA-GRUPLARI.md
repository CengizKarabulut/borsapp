# GLOBAL ve piyasa grupları

Bu paket, grafikteki varlığın durumunu ve seçilen piyasa grubunun 18 tarama
kuralını gösterir. **Grup dosyaları alarm, Telegram mesajı veya emir üretmez.**
Mevcut BIST alarm kaynakları ayrı kalır.

## Hangi göstergeyi açmalıyım?

| İhtiyaç | Kaynak | Zaman dilimleri |
| --- | --- | --- |
| Açtığım hisse, vadeli, coin veya emtianın durumu | `ATC_GLOBAL_18_COKLU_ZAMAN.pine` | 5 dk, 15 dk, 1 saat, 4 saat, 1 gün, 1 hafta |
| Bir listedeki seçili 10 varlığın durumu | `generated/` altındaki ilgili grup dosyası | 1 saat, 4 saat, 1 gün, 1 hafta |

GLOBAL, grafikte açtığınız sembolü izler. Grup dosyasının üyeleri ise kendi
kataloğundan gelir; grafiğin sembolünü değiştirmek grubun üyelerini değiştirmez.

## Katalog kapsamı

24 Ekim 2026 paketindeki listeler:

| Piyasa | Sembol | Grup | Dosya |
| --- | ---: | ---: | --- |
| ABD: S&P 500, Nasdaq-100 ve Dow bileşenlerinin tekrarsız birleşimi | 518 | 52 | `generated/us-index-equities/ATC_US_INDEX_EQUITIES_GRUP_18_01.pine` |
| VİOP: doğrulanmış yakın-vade sürekli `1!` serileri | 65 | 7 | `generated/viop-continuous/ATC_VIOP_CONTINUOUS_GRUP_18_01.pine` |
| Binance spot USDT: hacme göre seçilmiş, sınıflandırma filtresini geçen çiftler | 378 | 38 | `generated/crypto-coins/ATC_CRYPTO_COINS_GRUP_18_01.pine` |

ABD listesi, bu üç endeksin kaynak tablolarındaki tam birleşimidir; ABD'de
işlem gören bütün hisseleri kapsamaz. Birden fazla endeksteki aynı sembol bir
kez yer alır.

VİOP kapsamı **kısmidir**: resmi 67 dayanağın 65'i için TradingView sürekli
seri kodu doğrulanmıştır. `TLREF` ve `TRT131130T14` için doğrulanmış sürekli
vadeli kod bulunmadığından yerine farklı araç eklenmemiştir. `1!` serileri
vadeler arasında geçiş yapan serilerdir; işlem yapılacak vadenin emir kodu
olarak kullanılmaz. Kaynak sayfasının bulunması, hesabın grafik/hacim verisine
erişebildiğini tek başına kanıtlamaz.

Coin kataloğunun kaynağı TradingView CEX Screener'daki **Binance / Spot /
USDT** listesidir. 516 kaynak çiftin geçerli pozitif fiyatı ve son 24 saatlik
USD hacmi kontrol edildi. Her baz varlık bir kez alınır; USD hacmi azalan
sıradadır. Eşit hacimde çift kodu sırası belirleyicidir. Bu ölçü **işlem
hacmini** gösterir; sosyal medyada konuşulma sayısını ölçmez.

Kaynak coin sınıflandırmasına göre 13 **Stablecoins kategori etiketi**,
adında açıkça tokenlaştırılmış hisse/ETF yazan 95 kayıt, Euro olan 1 kayıt,
kategori eşleşmesi bulunmayan 14 kayıt ve en az bir boş kategori adayı olan
15 kayıt dışarıda bırakıldı. Etiket, tokenın kendisinin sabit fiyatlı olduğunu
kanıtlamaz; örneğin USUAL bu etiket nedeniyle dışlanmıştır. Altı baz kodun
birden çok kategori adayı vardır; hepsinin dolu ve izin verilen kategorileri
olduğu için korunmuş, belirsizlikleri ayrıca kaydedilmiştir. Eksik sınıfları
tahmin edip sayıyı 400'e tamamlamak yerine **378 çift** kullanılır.

Semboller `BINANCE:BTCUSDT` gibi gerçek Binance spot USDT serileridir; her
sembolün gerçek TradingView bağlantısı ve görünen adı doğrulanmıştır. Hacim
koşulları o çiftin kaynak hacmiyle hesaplanır; eksik veya yalnız tik sayısı
olan veri hacim olarak kabul edilmez. Katalog bütün coinleri, bütün borsaları
veya vadeli/perpetual çiftleri kapsamaz. İşlem yapılacak çift ile grafikteki
borsa kodunun aynı olduğunu kontrol edin.

Her paketin `catalogue.json` dosyası üyeleri, `manifest.json` dosyası kaynak
tarihini, kapsamı, grup aralıklarını ve dosya özetlerini saklar. Listeler
sabit birer görüntüdür; endeks değişiklikleri veya yeni coinler kendiliğinden
kataloğa eklenmez. Coin grup sırası seçim anındaki 24 saatlik USD hacmine
dayanır; üyeler ve hacim sırası grafik açıkken kendiliğinden güncellenmez.
Bu sıra gelecekteki başarı veya alış önceliği sıralaması değildir. Diğer
piyasalarda grup sırası başarı veya güç sıralaması değildir.

## TradingView'de kullanım

1. Pine Editor'de ilgili `.pine` kaynağını yeni gösterge olarak kaydedip
   grafiğe ekleyin. Normal mum grafiği kullanın.
2. Gösterge ayarlarında **Bu dosyadaki grup** değerini seçin. Her grup en
   fazla 10 semboldür; son grup daha az üye içerebilir.
3. Her zaman dilimindeki `↑ / ↓ / hesaplanan kural` sayısını okuyun.
   Hücrenin üzerine gelince kaynak mumun zamanı, veri/hacim bilgisi ve
   eşleşen kural numaraları görünür.
4. **Seçili üyenin 18 kuralını göster** seçeneğini açıp **Ayrıntı için
   gruptaki sıra** ile 1–10 arasında üye seçin. Son kısa grupta seçim son
   mevcut üyeye sınırlandırılır.
5. Eşleşme tablosunda daha fazla satır varsa **Eşleşme sayfası** değerini
   değiştirin. Bu tablo aynı sembolün farklı kural ve zaman dilimlerini ayrı
   satır olarak gösterebilir.

**Yalnız seçili grup hesaplanır.** Grup 1 açıkken diğer 37 coin grubu arka
planda taranmaz. Grup değiştirmek göstergeyi yeniden hesaplatır. Coin dosyası
`_01`, 378 sembolün tamamını 1–38 gruplarında içerir; son grupta 8 sembol
vardır. Örneğin 31–40'ıncı semboller için grup 4'ü seçin. Eski 2454'lük
toplulaştırılmış coin paketinin `_02` ve `_03` dosyaları kaldırılmıştır.

Bir seferde bir grup dosyasını görünür tutun. Ayrıntı tablosu GLOBAL'in
varsayılan sağ üst tablosuyla çakışabileceğinden grup ayrıntısını kullanırken
GLOBAL'i gizleyin. Canlı izleme için veri akan uygun bir ana grafik seçin;
kapalı seanstaki bir ana grafik bağımsız sürekli tarayıcı değildir. Kaynak
mum zamanını ve hesabınızdaki gecikmeli/gerçek zamanlı veri hakkını kontrol edin.

10 sembol × 4 zaman dilimi en fazla 40 farklı veri isteği oluşturur.
[TradingView sınırları](https://www.tradingview.com/pine-script-docs/writing/limitations/)
normal hesaplarda 40, Ultimate'ta 64 farklı isteğe izin verir. Bu sınırın
korunması bütün sembollerde hesap süresi veya veri erişimi garantisi değildir.

## Hücreleri ve Stop/TP'yi okuma

- **AL:** İlgili yükseliş koşulu şu an sağlanıyor.
- **↓ İZLE:** Düşüş koşulu sağlanıyor; açığa satış yetkisi anlamına gelmez.
- **—:** Hesaplanabilen kuralın koşulu şu an sağlanmıyor.
- **200 MUM / 60 MUM / 252 MUM:** O kuralın gereken en az geçmiş uzunluğu.
  Kullanılan pencere bundan kısadır; eksik mumların sayısı değildir.
- **HACİM YOK / TİK HACMİ / VERİ YOK / VERİ?:** İlgili hesap doğrulanamamıştır;
  bunları kesin olarak “sinyal yok” diye okumayın.
- **1G ÖZEL:** 17 numaralı kural yalnız günlük zaman diliminde çalışır.
- **MA YOK / SKOR?:** 18 numaralı kuralın uygun MA veya skor hesabı elde
  edilememiştir.

Açık kaynak mumun son fiyatı kullanılır; kapanmadan koşul değişebilir.
Görünüm, geçmişe dönük başarı testi değildir. Stop/TP değerleri halen
**kalibre edilmemiş referans fiyatlardır**. Fiyatlar kendi sembolünün adımına
yuvarlanır; pozitif ve yönüne göre sıralı plan oluşmazsa seviyeler gösterilmez.
GLOBAL'deki **STOP %**, giriş fiyatına göre stop mesafesidir; hesap bakiyesinin
riski veya başarı olasılığı değildir. Gruplarda bu mesafe eşleşme satırının
bilgi kutusunda bulunur. Vadeli kontrat çarpanı, teminat ve pozisyon büyüklüğü
bu referans fiyat tablosunda hesaplanmaz.

