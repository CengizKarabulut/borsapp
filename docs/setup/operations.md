# Çalıştırma rehberi

## Güvenli sıra

1. `.env.example` dosyasını `.env` olarak kopyalayın ve değerleri doldurun.
2. İlk aşamada `DELIVERY_MODE=disabled` bırakın.
3. PostgreSQL'i başlatın: `docker compose up -d postgres`.
4. Runtime bağımlılıklarını kurun: `python -m pip install -e ".[runtime]"`.
5. Ayarları doğrulayın: `borsapp --env-file .env config-check`.
6. Şemayı kurun: `borsapp --env-file .env db-init`.
7. BIST Tüm evrenini önce önizleyin:
   `borsapp --env-file .env universe-sync`.
8. Sayıları doğruladıktan sonra eşitlemeyi uygulayın:
   `borsapp --env-file .env universe-sync --apply`.
9. Bildirimsiz pilot çalıştırın:
   `borsapp --env-file .env scan-symbol ASELS --timeframe 1h`.
10. Shadow servislerini başlatın:
   `docker compose --profile runtime up -d --build`.

`BIST_ALL`, borsapy üzerinden BIST Tüm (`XUTUM`) endeksinin güncel
bileşenlerinden oluşur. `universe-sync` varsayılan olarak yalnız önizleme yapar;
`--apply` atomik uygular. Kaynak 300'den az üye döndürürse veya mevcut evreni
yüzde 10'dan fazla küçültmeye çalışırsa işlem güvenlik nedeniyle durur. Doğrulanmış
olağanüstü toplu değişikliklerde ayrıca `--allow-large-removal` gerekir. Hafta içi
09:30 İstanbul saatindeki `BIST universe sync` GitHub işi aynı güvenlik kapılarıyla
güncel üyeliği uygular ve her çalışmayı `universe_sync_runs` tablosuna kaydeder.

`scan-worker`, XIST işlem günlerini `exchange-calendars` üzerinden alır. Her
timeframe için watermark tutar; servis durmuşsa kaçırılmış kapanışları yeniden
işler. Eski catch-up barları Telegram'a bildirilmez. 45 dakikalık mumlar 10:00
seans çıpasından türetilir ve 17:30-18:00 arasındaki 30 dakikalık kuyruk mum
varsayılan olarak atılır.

Tüm-BIST döngüsünde tek bir sembolün veri hatası bütün evrenin watermark'ını
kilitlemez. Hata `scan_cycle_failures` tablosuna sembol ve hata türüyle yazılır,
döngü `completed_with_errors` olur ve diğer hisseler ilerler. Universe boşsa
başarılı görünmek yerine tarama açıkça hata verir.

`borsapy` BIST intraday verisi ücretsiz kullanımda yaklaşık 15 dakika gecikmeli
olabilir; sistem bu nedenle yalnız kapanmış barları değerlendirir. Ayrıntı:
[borsapy fiyat geçmişi](https://github.com/saidsurucu/borsapy#fiyat-ge%C3%A7mi%C5%9Fi).

MA Live, `ma_research_levels` tablosunda ilgili sembol/timeframe için etkin bir
araştırma kaydı yoksa bilinçli olarak `UNKNOWN` üretir. Zayıf veya bulunmayan
tarihsel kanıtı güncel fiyat yakınlığıyla yükseltmez.

MA Research yalnız canonical, kapanmış barlarla gözlemsel seviye kalitesi üretir;
Telegram'a doğrudan yazmaz. Tek sembol kontrolü:
`borsapp --env-file .env ma-research-symbol ASELS --timeframe 1d --bars 1000`.
Tüm evren yenilemesi:
`borsapp --env-file .env ma-research-universe --timeframe 1d --bars 1000`.
Destek ve direnç niteliği ayrı değerlendirilir; canlı fiyat yalnız araştırmada
nitelikli bulunan tarafta olduğunda MA Live girdisi oluşur. `MA research refresh`
GitHub işi manuel çalıştırmada 1h, 4h veya 1d seçilebilir. Zamanlanmış günlük
yenileme, Neon depolama optimizasyonu tamamlandıktan sonra repository variable
olarak `ENABLE_SCHEDULED_RESEARCH=true` verilerek açılır.

## Canlı yayın kapısı

Canlıya geçiş üç ayrı bilinçli koşula bağlıdır:

- shadow karşılaştırmaları kabul edilebilir olmalı,
- `.env` içinde `DELIVERY_MODE=live` bulunmalı,
- canlı compose override açıkça kullanılmalı:
  `docker compose -f compose.yaml -f compose.live.yaml --profile runtime up -d --build`.

Tek bot yeterlidir. `listener` yalnız Komut Merkezi konusundan ve izin verilen
kullanıcılardan komut kabul eder. `publisher` bütün konu başlıklarına merkezi
outbox üzerinden yazar. Advisory lock ikinci listener'ın aynı anda açılmasını
engeller. `command-worker`, `/tara SYMBOL --force` ve
`/taramalar SYMBOL --force` isteklerini 1h canonical frame üzerinde işler;
tamamlanma veya hata yanıtını aynı Komut Merkezi konusuna outbox ile bırakır.
Disabled/shadow modda listener iş kuyruğu oluşturmaz ve command worker iş çekmez.

## KAP haber akışı

`borsapp news-kap-sync --lookback-days 1` KAP bildirimlerini ortak haber
deposuna yazar ve bir bildirimi birden fazla BIST hissesine bağlayabilir. İlk
çalışma yalnız başlangıç referansı oluşturur; eski bildirimleri Telegram'a
göndermez. `--notify` yalnız `DELIVERY_MODE=live` iken kabul edilir ve yeni,
BIST ile eşleşmiş bildirimleri `TELEGRAM_TOPIC_NEWS` konusuna bırakır.

GitHub Actions zamanlaması varsayılan olarak kapalıdır. Hazır olduğunda
`ENABLE_SCHEDULED_NEWS=true` tanımlanır. Bildirimleri açmak ayrıca
`NEWS_DELIVERY_MODE=live` gerektirir; bu ikinci anahtar eklenmedikçe iş yalnız
veritabanını günceller.

## GitHub Actions

`Shadow scan` workflow'u manuel olarak çalıştırılabilir. Zamanlanmış hafta içi
çalışmalar, Neon depolama optimizasyonu tamamlandıktan sonra repository variable
olarak `ENABLE_SCHEDULED_SCANS=true` verilerek açılır. `DATABASE_URL` yoksa
başarıyla ve hiçbir şey yapmadan çıkar. Workflow `DELIVERY_MODE=shadow` değerini
zorlar ve doğrudan Telegram yayını yapmaz.

Manuel çalıştırmada varsayılan kapsam `symbol`, sembol `ASELS`'tir; bu seçenek
tek hisselik güvenli smoke testidir. `due-universe` kapsamı seçilirse ilgili
timeframe için zamanı gelen bütün BIST hisseleri taranır.

Bu iki zamanlama anahtarı varsayılan olarak kapalıdır. Böylece tüm BIST üzerinde
tam frame kopyaları henüz seyreltilmeden ücretsiz Neon kotası kendiliğinden
tüketilmez. `BIST universe sync` bu kapılardan bağımsız olarak günlük çalışır.

Canonical OHLCV barları snapshot başına tekrar edilmez. Aynı enstrüman,
timeframe, kaynak, fiyat bazı, seri revizyonu ve kapanış zamanı için tek satır
tutulur; snapshot yalnız pencere başlangıcı, sonu ve bar sayısını taşır. Kaynak
aynı `series_revision` altında geçmiş bir barı değiştirirse sistem sessizce
üzerine yazmak yerine hata verir ve revizyonun artırılmasını ister.

Üretimde uzun yaşayan Docker worker tercih edilir. GitHub Actions, shadow ve
yedek catch-up için uygundur; tek merkezi Telegram listener/publisher olarak
kullanılmaz.

## Kullanıcının sağlaması gereken altyapı

- Kalıcı PostgreSQL sunucusu ve `DATABASE_URL`/`COMPOSE_DATABASE_URL` değeri.
- İlk `BIST_ALL` eşitlemesinin önizlenip uygulanması; daha sonra günlük iş otomatik yürür.
- Shadow farkları kabul edildikten sonra bilinçli canlıya geçiş kararı.

`borsapy`, kendi dokümantasyonuna göre kişisel/eğitim amaçlı kullanıma yöneliktir.
Uygulama ticari olarak kullanılacaksa Borsa İstanbul veri lisansı ayrıca
değerlendirilmelidir.

Telegram topic ve GitHub değişkenleri dışında uygulama koduna secret yazılmaz.
