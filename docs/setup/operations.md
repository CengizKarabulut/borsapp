# Çalıştırma rehberi

## Güvenli sıra

1. `.env.example` dosyasını `.env` olarak kopyalayın ve değerleri doldurun.
2. İlk aşamada `DELIVERY_MODE=disabled` bırakın.
3. PostgreSQL'i başlatın: `docker compose up -d postgres`.
4. Runtime bağımlılıklarını kurun: `python -m pip install -e ".[runtime]"`.
5. Ayarları doğrulayın: `borsapp --env-file .env config-check`.
6. Şemayı kurun: `borsapp --env-file .env db-init`.
7. Pilot sembolü ekleyin:
   `borsapp --env-file .env instrument-register ASELS`.
8. Bildirimsiz pilot çalıştırın:
   `borsapp --env-file .env scan-symbol ASELS --timeframe 1h`.
9. Shadow servislerini başlatın:
   `docker compose --profile runtime up -d --build`.

`scan-worker`, XIST işlem günlerini `exchange-calendars` üzerinden alır. Her
timeframe için watermark tutar; servis durmuşsa kaçırılmış kapanışları yeniden
işler. Eski catch-up barları Telegram'a bildirilmez. 45 dakikalık mumlar 10:00
seans çıpasından türetilir ve 17:30-18:00 arasındaki 30 dakikalık kuyruk mum
varsayılan olarak atılır.

`borsapy` BIST intraday verisi ücretsiz kullanımda yaklaşık 15 dakika gecikmeli
olabilir; sistem bu nedenle yalnız kapanmış barları değerlendirir. Ayrıntı:
[borsapy fiyat geçmişi](https://github.com/saidsurucu/borsapy#fiyat-ge%C3%A7mi%C5%9Fi).

MA Live, `ma_research_levels` tablosunda ilgili sembol/timeframe için etkin bir
araştırma kaydı yoksa bilinçli olarak `UNKNOWN` üretir. Zayıf veya bulunmayan
tarihsel kanıtı güncel fiyat yakınlığıyla yükseltmez.

## Canlı yayın kapısı

Canlıya geçiş üç ayrı bilinçli koşula bağlıdır:

- shadow karşılaştırmaları kabul edilebilir olmalı,
- `.env` içinde `DELIVERY_MODE=live` bulunmalı,
- canlı compose override açıkça kullanılmalı:
  `docker compose -f compose.yaml -f compose.live.yaml --profile runtime up -d --build`.

Tek bot yeterlidir. `listener` yalnız Komut Merkezi konusundan ve izin verilen
kullanıcılardan komut kabul eder. `publisher` bütün konu başlıklarına merkezi
outbox üzerinden yazar. Advisory lock ikinci listener'ın aynı anda açılmasını
engeller.

## GitHub Actions

`Shadow scan` workflow'u hafta içi 10:00-18:00 İstanbul aralığına denk gelen
UTC saatlerinde 15 dakikada bir uyanır. `DATABASE_URL` yoksa başarıyla ve hiçbir
şey yapmadan çıkar. Workflow `DELIVERY_MODE=shadow` değerini zorlar ve doğrudan
Telegram yayını yapmaz.

Üretimde uzun yaşayan Docker worker tercih edilir. GitHub Actions, shadow ve
yedek catch-up için uygundur; tek merkezi Telegram listener/publisher olarak
kullanılmaz.

## Kullanıcının sağlaması gereken altyapı

- Kalıcı PostgreSQL sunucusu ve `DATABASE_URL`/`COMPOSE_DATABASE_URL` değeri.
- Başlangıç universe sembollerinin `instrument-register` ile eklenmesi.
- Shadow farkları kabul edildikten sonra bilinçli canlıya geçiş kararı.

Telegram topic ve GitHub değişkenleri dışında uygulama koduna secret yazılmaz.
