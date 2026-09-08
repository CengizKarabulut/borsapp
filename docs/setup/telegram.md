# Telegram forum kurulumu

Bu işlem bir kez kullanıcı tarafından yapılır. Bot token'ı veya kimlikler hiçbir
zaman Git'e commit edilmez.

## Neden tek bot?

Tek bot bütün konu başlıklarına yazabilir; hedef konu her istekte
`message_thread_id` ile seçilir. Tek bot:

- tek token ve tek yetki yüzeyi oluşturur,
- komut update offset'inin birden fazla listener arasında çakışmasını önler,
- aynı olayın farklı botlardan iki kez gönderilmesi riskini azaltır,
- tüm yayınları merkezi outbox üzerinden hız sınırlı ve denetlenebilir tutar.

Bu projede yalnız **bir merkezi update consumer** ve **bir merkezi publisher**
çalışacaktır. GitHub Actions tarama işleri doğrudan Telegram API'sine yazmaz.
Beklenen tek grup trafiği için ikinci bir bot gerekmez. Ancak ileride farklı
gruplar arasında güvenlik/yetki izolasyonu gerekirse ayrı bot yeni bir dağıtım
kararı olarak değerlendirilebilir.

## 1. Grup ve bot

1. Telegram'da bir **özel süpergrup** oluşturun.
2. Grup ayarlarından **Konular / Topics** özelliğini açın.
3. BotFather üzerinden yeni bir bot oluşturun ve token'ı güvenli yerde saklayın.
4. Botu gruba ekleyin. Mesaj gönderebilmesi, fotoğraf/dosya paylaşabilmesi ve
   konu mesajlarını okuyabilmesi için yönetici yetkisi verin.
5. BotFather'da botun grup gizlilik ayarını komut dinleme ihtiyacına göre
   kapatın. Komutlar yalnız aşağıdaki Komut Merkezi konusunda ve izin verilen
   kullanıcı kimliklerinden kabul edilecektir.

## 2. Açılacak konular

Adlar değişebilir; yapılandırmada sayısal topic ID kullanılır.

| Önerilen konu | İçerik | Ortam değişkeni |
| --- | --- | --- |
| Komut Merkezi | `/tara ASELS`, `/analiz ASELS` ve doğrudan yanıtlar | `TELEGRAM_TOPIC_COMMAND` |
| Taramalar | SIGNAL, TECHNICAL, MA ve confluence bildirimleri | `TELEGRAM_TOPIC_SCANS` |
| Analiz & Araştırma | Birleşik hisse araştırması | `TELEGRAM_TOPIC_ANALYSIS` |
| Grafikler | Grafik ve görsel çıktılar | `TELEGRAM_TOPIC_CHARTS` |
| Haberler & KAP | Şirket/piyasa haberleri ve KAP | `TELEGRAM_TOPIC_NEWS` |
| Takvim | Ekonomik ve şirket olay takvimi | `TELEGRAM_TOPIC_CALENDAR` |
| Raporlar & Bültenler | Günlük/haftalık özetler | `TELEGRAM_TOPIC_REPORTS` |
| Sistem | Shadow farkları, veri gecikmesi ve hata bildirimleri | `TELEGRAM_TOPIC_SYSTEM` |

Tüm tarama aileleri tek **Taramalar** konusunda birleşir; mesaj başlığı
`[SIGNAL]`, `[TECHNICAL]`, `[MA]` veya `[CONFLUENCE]` olarak ayrılır.
Bu, her scanner için ayrı Telegram konusu açıp konuları çoğaltmayı önler.

## 3. Kimlikleri alma

- Grup chat ID değeri çoğunlukla `-100...` biçimindedir.
- Topic ID, ilgili konu içindeki bir mesajın bağlantısındaki son sayıdır.
- Canlı listener çalışırken kendi botunuza `/kimlik` gönderin. Botun döndürdüğü
  `Kullanıcı ID` değerini `TELEGRAM_ALLOWED_USERS` olarak kaydedin; üçüncü taraf
  bir ID botuna gerek yoktur.
- Token'ı topic ID öğrenmek için üçüncü taraf sitelere yapıştırmayın.

Hazırlanacak değerler:

    TELEGRAM_CHAT_ID=-100...
    TELEGRAM_ALLOWED_USERS=123456789
    TELEGRAM_TOPIC_COMMAND=...
    TELEGRAM_TOPIC_SCANS=...
    TELEGRAM_TOPIC_ANALYSIS=...
    TELEGRAM_TOPIC_CHARTS=...
    TELEGRAM_TOPIC_NEWS=...
    TELEGRAM_TOPIC_CALENDAR=...
    TELEGRAM_TOPIC_REPORTS=...
    TELEGRAM_TOPIC_SYSTEM=...

Kimlik doğrulandıktan sonra yalnız listedeki kullanıcıların komut verebilmesi
için `TELEGRAM_ALLOW_CHAT_MEMBERS=false` yapın. Yalnızca statik izin listesini
kullanmak istiyorsanız `TELEGRAM_ALLOW_CHAT_ADMINS=false` da olmalıdır. Birden
fazla kullanıcı virgülle ayrılabilir: `123456789,987654321`.

## 4. Mesaj davranışı

- Zamanlanmış yayınlar içerik türünün sabit konusuna gider.
- Kullanıcı komutuna verilen kısa cevap Komut Merkezi'nde kalır.
- Komut uzun analiz/grafik üretirse Komut Merkezi'nde durum ve bağlantı
  gönderilir; asıl çıktı Analiz veya Grafikler konusuna yönlendirilebilir.
- Başka grup, başka topic veya izin verilmeyen kullanıcıdan gelen komut işlenmez.
- Sistem konusu başarısızlık ve shadow farkları içindir; normal başarı loglarıyla
  doldurulmaz.

## 5. Araştırma komutlarının çıktısı

- `/analiz ASELS`: Analiz & Araştırma konusuna tek ekran canonical özet.
- `/temel ASELS`: aynı konuya kaynak ve veri kapsamı etiketli finansal kart.
- `/rapor ASELS`: Raporlar & Bültenler konusuna 24 bölümlü PDF belge.

Bu üç komut uzun iş kuyruğuna alınır. Komut Merkezi önce iş kimliğini, işlem
bitince de başarı veya hata durumunu gösterir. PDF doğrudan bot tarafından dosya
olarak yüklenir; ayrı bir bağlantı veya ikinci bot gerekmez.
