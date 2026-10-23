# GitHub üzerinde güncel grup raporları

Güncel işletim ve Actions ekranı için
[Actions kullanım rehberini](ACTIONS_ISLETIM_REHBERI.md) kullanın.

630 hisseyi son gerçek mumla tarayan sekiz zaman dilimi, kesişim görselleri
ve sabah destek/direnç/pivot raporu geçici GitHub runner belleğinde hesaplanır.
Kalıcı PostgreSQL veya yerel bilgisayar gerekmez. Telegram teslim onayları
Actions artifact'larında tutulur. Raporların kapsamı ve gerçek fiyat zamanı
çıktılarda ayrı gösterilir; GitHub çalışma saati fiyat zamanı değildir.

Önceki Neon/veritabanı taramalarına ait otomatik işler ve tek seferlik deneme
workflow'ları kaldırıldı. `ENABLE_SCHEDULED_SCANS`,
`ENABLE_ATC_CLOUD_REPORT` ve benzeri eski değişkenleri açmak güncel RAM
raporlarını etkinleştirmez. Kullanılabilen dört güncel rapor, manuel bakım
işleri ve kaldırılan girişler yeni rehberde listelenir.

KAP/finansal arşiv ve Telegram komut botu ayrı, kalıcı veritabanı kullanan
hizmetlerdir. Bu hizmetlerin elle bakım işleri korunur; kapasite ve yayın
kuyruğu doğrulanmadan otomatik yeniden yazıma açılmazlar.

Gerekli gizli değerler Actions Secrets altında
`TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID`; mevcut konu yönlendirmeleri
Actions Variables altında tutulur. Değerleri Git'e veya sohbetlere yazmayın.
Bu depo kamusaldır: yüklenen tarama artifact'ları depo erişimi olanlara
açıktır. Kimlik bilgileri, ham özel hesap verileri ve oturum çerezleri
artifact'a konmaz.

GitHub cron gecikebilir; anlık veya tam dakikasında çalışma garantisi yoktur.
Açık mum raporu CANLI / TEYİTSİZ olarak işaretlenir.
Geçmişe göre kalibre edilmiş Stop/TP veya otomatik emir gönderimi bu
raporların tamamlandığı sonucundan çıkarılamaz.
