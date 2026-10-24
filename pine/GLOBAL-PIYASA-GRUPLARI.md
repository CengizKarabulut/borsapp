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
| TradingView Crypto Coins Screener kataloğu | 2454 | 246 | `generated/crypto-coins/ATC_CRYPTO_COINS_GRUP_18_01.pine` ile `_03.pine` |

ABD listesi, bu üç endeksin kaynak tablolarındaki tam birleşimidir; ABD'de
işlem gören bütün hisseleri kapsamaz. Birden fazla endeksteki aynı sembol bir
kez yer alır.

VİOP kapsamı **kısmidir**: resmi 67 dayanağın 65'i için TradingView sürekli
seri kodu doğrulanmıştır. `TLREF` ve `TRT131130T14` için doğrulanmış sürekli
vadeli kod bulunmadığından yerine farklı araç eklenmemiştir. `1!` serileri
vadeler arasında geçiş yapan serilerdir; işlem yapılacak vadenin emir kodu
olarak kullanılmaz. Kaynak sayfasının bulunması, hesabın grafik/hacim verisine
erişebildiğini tek başına kanıtlamaz.

Coin kataloğu, filtresiz Crypto Coins Screener dışa aktarımındaki 2454 kaydın
tamamıdır; sıralaması olmayan 51 kayıt da dahildir. Gerçek `CRYPTO:` kodları
TradingView bağlantılarından alınmıştır. Bunlar toplulaştırılmış USD coin
serileridir; bütün borsaların bütün işlem çiftleri değildir. Örneğin bir
`CRYPTO:` serisinin fiyatı ve hacmi seçtiğiniz borsanın `BTCUSDT` paritesiyle
birebir olmak zorunda değildir.

Her paketin `catalogue.json` dosyası üyeleri, `manifest.json` dosyası kaynak
tarihini, kapsamı, grup aralıklarını ve dosya özetlerini saklar. Listeler
sabit birer görüntüdür; endeks değişiklikleri veya yeni coinler kendiliğinden
kataloğa eklenmez. Grup sırası bir başarı veya güç sıralaması değildir.

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

**Yalnız seçili grup hesaplanır.** Grup 1 açıkken diğer 245 coin grubu arka
planda taranmaz. Grup değiştirmek göstergeyi yeniden hesaplatır. Coin dosyası
`_01` genel 1–100, `_02` genel 101–200, `_03` genel 201–246 gruplarını içerir.
Örneğin genel grup 201 için `_03` dosyasını açıp yerel grup 1'i seçin.

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

