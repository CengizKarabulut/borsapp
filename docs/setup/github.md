# GitHub Actions kurulumu

Güncel iş adları ve elle kullanım:
[Actions kullanım rehberi](../ACTIONS_ISLETIM_REHBERI.md).
Tarama zamanları:
[otomatik tarama takvimi](../ATC_AUTOMATIC_SCHEDULE.md).

## Grup raporları

1. Repository → Settings → Secrets and variables → Actions → Secrets:
   `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID`.
2. Variables altında mevcut zaman dilimi konu yönlendirmelerini ve
   `TELEGRAM_TOPIC_REPORTS` değerini koruyun.
3. Actions → **ATC manual live candle snapshot** → Run workflow →
   Branch **main**, seçilen zaman dilimi, `delivery=preview`.
4. Kapsam ve kaynak zamanını inceleyin. Gruba göndermek için
   `delivery=publish` seçin. Yayın yalnız main üzerinden yapılır.
5. Otomatik sekiz zaman dilimi raporu ve sabah raporu main üzerindeki
   workflow takvimleriyle çalışır. Eski `ENABLE_SCHEDULED_SCANS` veya
   `SCAN_DELIVERY_MODE` bu RAM akışının açma/kapama anahtarı değildir.

Her zaman dilimi kendi mevcut Telegram konusuna gider. Güncel yön bildirim
politikası uygulanır; koşullar, kesişimler ve tam CSV aynı paketten üretilir.
Destek/direnç raporu tüm 630 hisseyi en çok 20 satırlık sayfalarla gönderir.
Token/parola/oturum bilgilerini dosyalara, iş günlüklerine veya artifact'a
koymayın. Rapor artifact'larının public depoda erişilebilir olduğunu unutmayın.

## Ayrı kalıcı bot ve finansal arşiv

PostgreSQL'e bağlı komut botu, haberler, MA araştırması, sonuç ölçümü ve evren
eşitleme işleri **Maintenance** altında yalnız elle kullanılabilir.
Güncel grup taramaları bunlara bağlı değildir. Bu işlerin yeniden otomatik
çalışması için veritabanı kapasitesi ve tek dinleyici ayrıca doğrulanmalıdır.

`DATABASE_URL` yalnız bu ayrı hizmetler için gerekir. Komut yetkileri için
`TELEGRAM_ALLOWED_USERS` gerçek kullanıcı ID'lerini içermelidir.
`TELEGRAM_ALLOW_CHAT_ADMINS` / `TELEGRAM_ALLOW_CHAT_MEMBERS` geniş yetki
ayarları bilinçli olarak kullanılmalıdır. Aynı bot için iki listener açmayın.

## Repo ayarları

Main için branch protection ve CI kontrollerini koruyun. Actions varsayılan
izinlerini salt okunur tutun; yayın işleri yalnız gerekli bot değerlerini
kullanır. `_legacy` altındaki dosyalar Actions girişleri değildir ve bir
bölümü compatibility/parite kodu tarafından hâlâ kullanılır.
