# Market Telegram Suite

BIST grafik üretimi, teknik piyasa taraması ve bütünleşik hisse araştırmasını
tek repoda iki bağımsız Telegram botuyla çalıştıran monorepo.

## Uygulamalar

| Uygulama | Dizin | Telegram komutları |
| --- | --- | --- |
| Grafik botu | `apps/chart_bot` | `/grafik`, `/kareler`, `/grafikyardim` |
| Teknik / araştırma botu | `apps/technical_bot` | `/analiz`, `/rapor`, `/temel`, `/tara`, `/liste`, `/takip`, `/esik`, `/durum`, `/gecmis` |

`/rapor SYMBOL`, güncel `/analiz SYMBOL` araştırma paketinin geriye dönük
uyumluluk takma adıdır; ayrı bir eski rapor motoru yoktur. `/temel SYMBOL`
sektör uyarlamalı temel analiz kartını üretir. `/analiz SYMBOL` ise tek akışta
araştırma özeti, temel analiz radar kartı, günlük hareketli ortalama tablosu ve
16:9 teknik grafik üretir.

`/analiz` çıktısı otomatik AL/SAT kararı değildir. Şirket kalitesi, 8 çeyreklik
bilanço trendi, kâr kalitesi, sektör-göreli değerleme, teknik yapı, kritik
seviyeler ve kanıtlanabilir ana risk ayrı katmanlar olarak değerlendirilir.
Eksik veri kötü veri sayılmaz ve puan uydurulmaz.

## Telegram mimarisi

İki bot aynı Telegram forum grubunda çalışabilir; her bot yalnız kendi
`chat_id + message_thread_id` hedefini dinler ve gönderim yapar. BotFather
token'ları farklı olmalıdır. Aynı token iki `getUpdates` dinleyicisinde
kullanılmamalıdır.

Teknik/araştırma akışı doğrudan bu reponun teknik botunu kullanır; başka bir
repo, Telethon session veya harici chat ID zinciri kullanılmaz.

## GitHub Actions secrets

Repository **Settings → Secrets and variables → Actions** bölümünde:

| Secret | Açıklama |
| --- | --- |
| `CHART_BOT_TOKEN` | Grafik botunun BotFather token'ı |
| `TECHNICAL_BOT_TOKEN` | Teknik/araştırma botunun BotFather token'ı |
| `TELEGRAM_CHAT_ID` | Ortak forum grubunun `-100...` kimliği |
| `CHART_TOPIC_ID` | Grafik botu konu kimliği |
| `TECHNICAL_TOPIC_ID` | Teknik rapor, temel analiz ve araştırma raporunun konu kimliği |
| `TELEGRAM_ALLOWED_USERS` | Teknik botu kullanabilecek Telegram kullanıcı kimlikleri; isteğe bağlı |

GitHub Actions içindeki dinleme zincirleri, workflow'un `actions: write` iznine
sahip repoya sınırlı `GITHUB_TOKEN` değerini otomatik kullanır; ayrıca PAT
zorunlu değildir.

## Araştırma çıktısı

`/analiz ZGYO` benzeri bir komut dört görsel gönderir:

1. **Araştırma özeti:** şirket kalitesi, bilanço trendi, kâr kalitesi,
   değerleme, teknik yapı, ana risk ve kritik seviyeler.
2. **Temel analiz kartı:** sektör profiline göre beş faktörlü radar ve yıldızlı
   skor görünümü. Düşük veri kapsamlı faktörler puanlanmaz.
3. **Hareketli ortalamalar:** günlük SMA 5/8/13, 21/34/55 ve 89/144/233;
   değer, fiyata göre konum, eğim ve kısa/orta/uzun vade dizilim özeti.
4. **Teknik grafik:** 16:9 mum grafiği + Bollinger + AlphaTrend + piyasa
   yapısı/seviyeler; alt panellerde hacim, MACD, SMI, RSI divergence, OBV ve ATR.

Teknik gösterge hesapları kullanıcı tarafından sağlanan Pine mantığıyla aynı
katmanda tutulur. AlphaTrend BUY/SELL etiketleri ürün tercihi gereği raporda
bastırılır; otomatik işlem çağrısı üretilmez.

## Teknik seviye ve takip ilkeleri

- Teknik destek daima referans fiyatın altında, direnç üstünde olmak zorundadır.
- `/takip` ham son pivotu körlemesine kullanmaz; son **teyitli kapanışın** iki
  yanındaki teyitli swing seviyelerini seçer.
- Daha önce aşağı kırılmış bir swing dip fiyatın üzerinde kalıyorsa artık
  “alt eşik” değildir; yukarı reclaim/rol değişimi adayı olarak ele alınır.
- Takip invariantı `alt eşik < teyitli kapanış < üst eşik` sağlanmadan kayıt
  oluşturulmaz.
- Uyarılar canlı/tamamlanmamış muma göre değil, yalnız tamamlanmış seçili zaman
  dilimi mumunun kapanışına göre değerlendirilir.
- Eski watchlist kayıtları yeni invariantlara uymuyorsa alarm üretmeden önce
  otomatik yeniden hesaplanır.

## Temel / değerleme / risk ilkeleri

- Finansal trendler mümkün olduğunda son **8 çeyrek + TTM** üzerinden okunur.
- Kâr kalitesinde CFO/net kâr, FCF, accrual ve işletme sermayesi ayrışmaları
  kullanılır.
- Bankalarda klasik net borç yaklaşımı uygulanmaz; resmi SYR/NPL veri kaynağında
  yoksa uydurulmaz.
- GYO'da NAV/ekspertiz verisi yoksa bu eksiklik açıkça belirtilir.
- Değerleme şirket kalitesinden ayrı tutulur ve araştırma skorunda iki kez
  sayılmaz.
- Değerleme sektör metadata'sı yeterliyse sektör eşlerine, değilse açıkça BIST
  geneline göre yapılır.
- Uzak/eski seviyeler aksiyon seviyesi olarak gösterilmez.
- Risk yalnız mevcut kanıttan üretilir; veri yokluğu otomatik `50/100 risk`
  sayılmaz.

## Aktif workflow'lar

- `chart-bot.yml`: grafik komut botunun dinleyicisi
- `chart-generate.yml`: manuel grafik üretimi
- `technical-bot.yml`: teknik/temel/araştırma komut botunun dinleyicisi ve tarama zamanlayıcısı
- `technical-scan.yml`: yalnız bot/manuel dispatch ile çalışan BIST taraması
- `research-report-smoke.yml`: GARAN/ZGYO/ASELS bütünleşik araştırma ve seviye-invariant kalite kontrolü
- `research-telegram-send.yml`: güncel araştırma paketinin manuel üretim/gönderim doğrulaması
- `ci.yml`: iki uygulamanın testleri ve Ruff kontrolleri

Eski standalone `technical-report.yml` ve onun gönderim kodu kaldırılmıştır.
Ayrı `fundamental-card-smoke.yml` da daha kapsamlı araştırma smoke testi aynı
alanı zaten doğruladığı için tutulmaz.

Bot workflow'ları farklı token, topic, concurrency grubu, cache ve offset
dosyaları kullanır; birbirlerinin Telegram güncellemelerini tüketmez.

## Yerel test

```bash
cd apps/chart_bot
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v

cd ../technical_bot
python -m pip install -r requirements.txt -r requirements-dev.txt
ruff check src tests
python -m unittest discover -s tests -v
```

Uygulamaların ayrıntılı metodoloji belgeleri kendi dizinlerindedir.

## Geçiş geçmişi

Bu repo aşağıdaki iki kaynak reponun Git geçmişlerini git subtree ile içerir:

- `CengizKarabulut/market-chart-lab` → `apps/chart_bot`
- `CengizKarabulut/stock-technical-telegram` → `apps/technical_bot`

Eski kaynak repolar arşiv niteliğindedir; aktif geliştirme
`market-telegram-suite` üzerinde devam eder.
