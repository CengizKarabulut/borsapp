# market-chart-lab

BIST hisseleri, yabancı hisseler ve kripto paralar için **göstergeli fiyat grafiği** üretir.
Aynı veriden iki çıktı çıkar:

- **PNG** — Telegram'a fotoğraf olarak gönderilebilen statik grafik
- **HTML** — zoom, hover ve seri açıp kapatma destekli etkileşimli sayfa (Plotly)

`stock-technical-telegram` deposundan farkı: orada göstergeler sayı ve tablo olarak
raporlanıyordu, burada **grafiğin üstünde çiziliyor**.

Göstergeler tek bir dev grafiğe yığılmaz; her biri 2–4 katman taşıyan **odaklı karelere**
bölünür. Bollinger'e bakarken MACD gürültüsü, momentuma bakarken bulut karmaşası ekranı
meşgul etmez.

---

## Göstergeler

Dört kategoriden toplam 19 gösterge. Kareler her kategoriden birer tane seçer.

| Kategori | Göstergeler |
|---|---|
| **Trend** | EMA/SMA, Supertrend, Ichimoku, Parabolic SAR, ADX/DMI |
| **Momentum** | RSI, MACD, Stochastic RSI, CCI, Williams %R, Awesome Oscillator |
| **Volatilite** | Bollinger, ATR, Keltner, Donchian |
| **Hacim** | Hacim/RVOL, VWAP, OBV, Volume Profile (VPVR) |

Wilder yumuşatması (`rma`) kullanan göstergelerde TradingView ile aynı sonuç hedeflenmiştir.
Dört ayrıntı özellikle önemsenmiştir:

- **Ichimoku kaydırması** TradingView'daki gibi `displacement - 1` bardır (varsayılan 26
  ayarında 25 bar). Bu atlanırsa bulut bir bar kayar.
- **VWAP çapası** aralığa göre seçilir: gün içi barlarda seans başında sıfırlanan kümülatif
  VWAP, günlük ve üzeri barlarda 20 barlık hareketli VWAP. Günlük barda seans çapası
  kullanılırsa her grup tek bardan oluşacağı için VWAP fiyata eşitlenir.
- **Parabolic SAR** dönüş anlarında son iki barın ucuna kırpılır; bu kırpma atlanırsa
  gösterge fiyatın içine girip yanlış sinyal üretir.
- **Volume Profile** her barın hacmini yüksek–düşük aralığına eşit dağıtır (yalnızca
  kapanışa bakmaz) ve **görünen pencereden** hesaplanır, tüm geçmişten değil.

---

## Kareler ve ızgara

Varsayılan çalıştırma dört kare üretip **tek bir görselde 2×2 ızgara** olarak birleştirir.

**Her karenin yapısı aynı: mum grafiğinin üstünde TEK gösterge, altında kendi ölçeğine
sahip ÜÇ panel.** Fiyat panelinde birden fazla katman üst üste binince grafik okunmaz hale
geliyor; bu kural bir testle korunuyor.

| Kare | Fiyat üstünde | Panel 1 | Panel 2 | Panel 3 |
|---|---|---|---|---|
| Klasik | EMA/SMA *(trend)* | RSI *(momentum)* | Bollinger %B *(volatilite)* | Hacim *(hacim)* |
| Trend takip | Supertrend *(trend)* | MACD *(momentum)* | ATR *(volatilite)* | OBV *(hacim)* |
| Bulut ve kanal | Ichimoku *(trend)* | Stoch RSI *(momentum)* | Keltner konumu *(volatilite)* | VWAP sapması *(hacim)* |
| Kırılım ve dönüş | Parabolic SAR *(trend)* | CCI *(momentum)* | Donchian konumu *(volatilite)* | RVOL *(hacim)* |

Doğası gereği fiyat üstüne binen volatilite göstergeleri panel biçimine çevrilmiştir:
Bollinger yerine **%B** (fiyatın bantlar içindeki konumu), Keltner yerine **kanal içi konum**
(0 = orta bant, ±1 = bantlar), Donchian yerine **kanal yüzdesi** (0 = dip, 100 = tepe),
VWAP yerine **yüzde sapma**. Böylece bilgi kaybolmadan mum grafiği temiz kalır.

Beşinci bir kare de var: `profil` (Volume Profile + Williams %R + bant genişliği + ADX).
Varsayılan sette değil, `--views profil` ile çağrılır.

```bash
python -m src.cli --symbol THYAO                  # 2x2 izgara, tek PNG
python -m src.cli --symbol THYAO --grid 4         # 1x4 yan yana
python -m src.cli --symbol THYAO --grid 0         # birlestirme yok, ayri PNG'ler
python -m src.cli --symbol THYAO --views klasik   # tek kare
python -m src.cli --symbol THYAO --views tumu     # on gosterge tek karede
```

Bir setteki tüm kareler **aynı x aralığını** paylaşır; Ichimoku projeksiyonu varsa hepsine
uygulanır, böylece ızgarada karolar hizalı durur.

Tüm kareler tek veri çekimi ve tek hesap turuyla üretilir.

### Çoklu periyot

```bash
python -m src.cli --symbol TMPOL --interval 4h,1d,1wk,1mo --telegram
```

**Windows PowerShell'de değeri tırnak içine alın:**

```powershell
python -m src.cli --symbol TMPOL --interval "4h,1d,1wk" --telegram
```

Tırnaksız yazıldığında PowerShell `1d` ifadesini ondalık sayı literali sayar ve `1`'e
çevirir; Python'a `4h,1,1wk` ulaşır. Aynı tuzak `1mb`, `1kb`, `1gb` gibi son eklerde de
vardır.

Her periyot için ayrı bir ızgara üretilir ve Telegram'a ayrı ayrı gönderilir. Bir periyot
başarısız olursa (örneğin saatlik veri gelmezse) diğerleri yine üretilir.

**Bar sayısı periyoda göre ayarlanır.** Sabit 250 kullanılsa aylık grafikte 20 yıllık geçmiş
sıkışır ve mumlar bir piksele iner. Varsayılanlar: gün içi ve günlük 250, haftalık 180,
aylık 96. `--bars` verilirse bu tablo devre dışı kalır.

**4 saatlik barlar türetilmiştir.** Ne yfinance ne borsapy 4 saatlik bar sunuyor; saatlik
veri çekilip birleştiriliyor. Birleştirme takvim saatine göre değil **gün sınırlarına göre**
yapılır: `pd.resample("4h")` barları 00:00, 04:00, 08:00 sınırlarına hizalar, bu da BIST'in
10:00–18:00 seansında günün ilk barını bir önceki günün kovasına atardı. Bunun yerine her
günün barları kendi içinde gruplanır.

Günün son kovası eksikse önceki kovaya katılır. borsapy BIST için günde 9 saatlik bar
döndürüyor (09:00–17:00); 4'e bölününce 4+4+1 olur ve tek saatlik bar kendi başına sahte bir
"4 saatlik" bar gibi görünürdü — açılış, yüksek, düşük ve kapanışı aynı olan boş bir mum.
Şimdi 4+5 olarak gruplanıyor, günde iki bar çıkıyor.

### Veriyi dürüst gösteren üç davranış

**Tamamlanmamış son bar.** Seans açıkken çekilen veride son bar hâlâ oluşuyordur; RVOL,
RSI ve günlük değişim gün kapanınca değişir. Yarım seansta RVOL doğal olarak 1'in çok
altında görünür ve bu yanıltıcıdır. Bar açıksa başlıkta `SON BAR AÇIK` uyarısı çıkar, kare
künyesine `● bar açık` eklenir ve o mum soluk çizilir.

Tespit gün içi ve günlük barlarda farklı çalışır. Gün içinde bar süresi yeterlidir. Günlük
ve üstünde ayrıca **seans kapanışı** dikkate alınır: BIST günlük barı `09:00` damgası taşır,
yalnızca süreye bakılsa bar ertesi sabah 09:00'a kadar açık sayılır ve seans bittikten saatler
sonra bile yanlış uyarı verirdi. Kapanış saatleri piyasaya göre ayarlıdır (BIST 18:15,
yabancı hisse 16:15, kripto 7/24 olduğu için yalnızca süre).

**Logaritmik fiyat ekseni.** 100'den 700'e çıkan bir seride lineer eksen ilk ayları ezer.
Görünen aralıkta yüksek/düşük oranı 4'ü aşarsa eksen otomatik log'a geçer; `--scale log`
veya `--scale linear` ile zorlanabilir.

**Aykırı hacim kırpma.** Tek bir devasa hacim barı panelin geri kalanını düz çizgiye
çevirir. Tavan 95. yüzdeliğe göre belirlenir, tavanı aşan barlar mor renkle işaretlenir ve
panel başlığında `3 bar kırpıldı` yazar — aykırı değer gizlenmez, sadece ölçek okunur olur.

### Görünüm

Tema TradingView'ın koyu düzenine yakındır: fiyat ekseni sağda, her işaretli serinin son
değeri kendi renginde bir kutucuk olarak sağ kenarda, panellerin sol üstünde `RSI (14) 56,10`
biçiminde satır içi künye. Sayılar Türkçe biçimlenir (`1.234,56`), ay adları Türkçedir.
Bunlar `locale` ayarından bağımsız yapılır; GitHub Actions'ta Türkçe locale kurulu olmayabilir.

Logaritmik eksende etiketlerdeki gereksiz sıfırlar atılır. Aksi halde aynı eksende `5,000`
(beş) ile `500,00` (beş yüz) yan yana düşer ve okunmaz hale gelir; artık `5` ve `500` yazar.

Sağdaki değer etiketleri çakışırsa dikeyde itilir — etiketteki **sayı değişmez**, yalnızca
çizim konumu kayar.

---

## Kurulum

```bash
git clone https://github.com/<kullanici>/market-chart-lab.git
cd market-chart-lab
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Kullanım

```bash
# BIST, günlük, altı kare, hem PNG hem sekmeli HTML
python -m src.cli --symbol THYAO

# Yabancı hisse, saatlik, iki kare
python -m src.cli --symbol AAPL --interval 1h --bars 200 --views momentum,bollinger

# Kripto, serbest gösterge listesi (tek kare üretir)
python -m src.cli --symbol BTC-USD --indicators ma,bbands,rsi,macd --no-png

# Açık zemin teması, geniş PNG
python -m src.cli --symbol ASELS --theme paper --width 2000

# Telegram'a gönder: PNG'ler albüm, HTML dosya olarak
python -m src.cli --symbol GARAN --telegram
```

Çıktılar `out/` klasörüne yazılır.

### Sembol yazımı

| Yazım | Sonuç |
|-------|-------|
| `THYAO` | BIST (borsapy) |
| `AAPL` | yabancı hisse (yfinance) |
| `BTC-USD`, `ETH` | kripto (yfinance) |
| `bist:YENIK` | BIST'e zorla |
| `yf:ASELS.IS` | yfinance'a zorla |
| `crypto:SOL` | `SOL-USD` olarak çözülür |

`AAPL` ile `THYAO` biçimsel olarak ayırt edilemediği için `src/bist_symbols.py` içinde
bir BIST kod listesi tutulur. Yeni halka arzlardan sonra tazelemek için:

```bash
python -m src.bist_symbols --refresh
```

Listede olmayan bir kodu tek seferlik kullanmak için `bist:` öneki yeterlidir.

### Önemli parametreler

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `--interval` | `1d` | Tek veya virgüllü liste: `4h,1d,1wk` → her biri için ayrı görsel |
| `--bars` | aralığa göre | Bar sayısı. Verilmezse: gün içi/günlük 250, haftalık 180, aylık 96 |
| `--period` | aralığa göre | Çekilecek geçmiş; göstergeler tüm geçmişte hesaplanıp sonra kırpılır |
| `--views` | `set` | `set` (4 kare ızgara), `all` (tümü) veya virgüllü görünüm listesi |
| `--grid` | `2` | Izgara sütun sayısı. `0` = birleştirme yok |
| `--indicators` | — | Görünüm yerine serbest gösterge listesi; tek kare üretir |
| `--scale` | `auto` | `auto` (oran 4'ü aşarsa log), `log`, `linear` |
| `--theme` | `tv` | `tv` (TradingView koyu), `ink`, `paper` (açık) |
| `--project-bars` | `25` | Ichimoku bulutunun fiyatın kaç bar önüne taşınacağı |
| `--embed-js` | kapalı | Plotly'yi HTML içine gömer; çevrimdışı açılır (~3 MB) |

---

## Mimari

```
src/
  views.py          kare tanımları: hangi göstergeler hangi karede
  bot.py            Telegram komut botu (uzun bağlantı ile dinleme)
  bot_runner.py     Actions içinde zinciri sürdüren çalıştırıcı
  compose.py        kareleri tek görselde ızgaraya dizen katman
  format.py         Türkçe sayı ve tarih biçimleme (locale'den bağımsız)
  data_sources.py   sembol çözümleme + borsapy/yfinance yönlendirme ve yedekleme
  bist_symbols.py   BIST kod listesi (tazelenebilir)
  indicators.py     10 göstergenin saf pandas hesabı — çizim bağımlılığı yok
  plotspec.py       "ne çizilecek" tarifi: Trace / Panel / ChartSpec
  render_png.py     matplotlib arka ucu
  render_html.py    plotly arka ucu + sayfa kabuğu
  theme.py          renk ve yazı tipi belirteçleri (iki arka uç da buradan okur)
  pipeline.py       veri → gösterge → tarif akışı
  telegram.py       fotoğraf ve dosya gönderimi
  cli.py            komut satırı
```

Tasarımın özü: **gösterge hesabı ile çizim ayrıdır**, ve iki arka uç aynı `ChartSpec`
nesnesini tüketir. Yeni bir gösterge eklemek için `indicators.py`'ye hesabı,
`plotspec.py`'ye bir builder yazmak yeterlidir; PNG ve HTML kendiliğinden günceller.
Yeni bir kare eklemek içinse `views.py`'ye tek bir `View` satırı yazmak yeter.

Her iki arka uçta da x ekseni tarih değil **bar konumudur**; etiketler sonradan takılır.
Bu sayede hafta sonu ve tatil boşlukları oluşmaz ve iki çıktı bar bar örtüşür.

## Telegram

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="-100..."
export TELEGRAM_TOPIC_ID="18"        # istege bagli, forum gruplari icin
python -m src.cli --symbol THYAO --telegram
```

Windows PowerShell'de:

```powershell
$env:TELEGRAM_BOT_TOKEN = "123456:ABC..."
$env:TELEGRAM_CHAT_ID   = "-1003502567927"
$env:TELEGRAM_TOPIC_ID  = "18"
python -m src.cli --symbol THYAO --telegram
```

**Konu (topic) numarası:** grup forum modundaysa mesajın doğru konuya düşmesi için
`message_thread_id` gerekir. Numara `web.telegram.org` bağlantısının sonundaki sayıdır:
`https://web.telegram.org/a/#-1003502567927_18` → chat id `-1003502567927`, konu `18`.
Boş bırakılırsa mesaj grubun genel akışına gider.

Izgara görseli **dosya olarak** gönderilir. Fotoğraf olarak gönderilseydi Telegram uzun
kenarı ~1280 piksele indirir ve künyelerdeki rakamlar okunmaz hale gelirdi.

## Telegram botu

Gruptan komutla grafik üretir:

```powershell
$env:TELEGRAM_BOT_TOKEN = "..."
$env:TELEGRAM_CHAT_ID   = "-1003502567927"
$env:TELEGRAM_TOPIC_ID  = "18"
python -m src.bot
```

Bot açık kaldığı sürece gruptaki komutları dinler. **Bilgisayar kapanırsa komutlar
çalışmaz** — sürekli çalışma seçenekleri aşağıda.

| Komut | Sonuç |
|---|---|
| `/grafik TMPOL` | dört periyot (4h, 1d, 1wk, 1mo) için ızgara |
| `/grafik ASELS 1d` | tek periyot |
| `/grafik BTC-USD 4h,1d` | seçili periyotlar |
| `/kareler` | hangi karelerin üretildiğini yazar |
| `/grafikyardim` | komut listesi |

### Aynı grupta birden fazla bot

Komut adları bilerek benzersiz seçilmiştir (`/grafik`, `/kareler`, `/grafikyardim`).
`/yardim` gibi genel adlar başka botlarda da bulunduğu için **yalnızca açıkça
adreslendiğinde** işlenir:

| Yazılan | Bu bot |
|---|---|
| `/grafik TMPOL` | cevap verir |
| `/grafik@BotAdınız TMPOL` | cevap verir |
| `/grafik@BaşkaBot TMPOL` | sessiz kalır |
| `/yardim` | sessiz kalır (çakışmayı önlemek için) |
| `/yardim@BotAdınız` | cevap verir |
| `/rapor THYAO` (başka botun komutu) | sessiz kalır, "bilinmeyen komut" bile yazmaz |

Bot kendi kullanıcı adını `getMe` ile öğrenir.

**Konu kısıtı:** `TELEGRAM_TOPIC_ID` tanımlıysa yalnızca o konudan gelen komutlar işlenir.
Forum modundaki gruplarda bot her konu başlığında cevap vermesin diye. Boş bırakılırsa
gruptaki tüm konular kabul edilir.

Cevap, komutun geldiği konuya düşer. Uzun yoklama (long polling) kullanılır; açık port
veya web kancası gerekmez, ev bilgisayarında çalışır.

**Güvenlik:** yalnızca `TELEGRAM_CHAT_ID` ile eşleşen sohbetten gelen komutlar işlenir.
Token'ı bilen biri botu kendi grubuna ekleyebilir; o gruptan gelen komutlara bot sessiz kalır.

### Botu sürekli çalışır tutmak

**GitHub Actions üzerinde zincir (önerilen).** Monorepo kökündeki
`.github/workflows/chart-bot.yml`
tek koşu içinde **50 dakika boyunca sürekli dinler**, süre dolunca kendini yeniden
tetikler ve zincir devam eder. Komutlara saniyeler içinde cevap gelir.

Sık cron (`*/5 * * * *`) kullanılmamasının sebebi: GitHub'ın beş dakikalık programları
pratikte çoğu zaman atlanır, komutlar dakikalarca cevapsız kalır. Buradaki saatlik cron
yalnızca zincir koparsa (hata, iptal, kota) devreye giren emniyet ağıdır.

Gerekli repository secret'ları: `CHART_BOT_TOKEN`, `TELEGRAM_CHAT_ID` ve
`CHART_TOPIC_ID`. Workflow bu değerleri uygulamanın beklediği ortam değişkenlerine
eşler. Dinleme zinciri için ayrıca PAT gerekmez: workflow'un `actions: write` iznine
sahip, repoya sınırlı ve kısa ömürlü `GITHUB_TOKEN` değeri `workflow_dispatch`
çağrısında otomatik kullanılır.

Zinciri **bir kez elle başlatmak** gerekir:
`Actions → Grafik Telegram Botu → Run workflow`.
Koşu 50 dakika "çalışıyor" görünür; bu normal, dinliyor demektir. Durdurmak için çalışan
koşuyu iptal edin (cron bir sonraki saat başında yeniden başlatır) ya da workflow'u
Actions sekmesinden devre dışı bırakın.

İşlenen son güncelleme `state/telegram_offset.json` dosyasına yazılır ve Actions
önbelleğinde saklanır. Böylece koşular arasında yazılan komutlar kaybolmaz ve aynı komut
iki kez işlenmez.

**Kendi bilgisayarında.** Anında cevap, kota yok, ama bilgisayar açık kalmalı:

```powershell
python -m src.bot                 # süresiz dinler
python -m src.bot --minutes 50    # süreli
python -m src.bot --once          # bekleyenleri işle ve çık
```

Açılışta otomatik başlatmak için Görev Zamanlayıcı:

```powershell
$exe = "$HOME\Documents\Codex\market-telegram-suite\apps\chart_bot\.venv\Scripts\python.exe"
$dir = "$HOME\Documents\Codex\market-telegram-suite\apps\chart_bot"
$action  = New-ScheduledTaskAction -Execute $exe -Argument "-m src.bot" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "MarketChartLabBot" -Action $action -Trigger $trigger
```

## GitHub Actions

`Actions → Grafik Üret → Run workflow` ile sembol, aralık ve kare seti seçilerek çalıştırılır.
Çıktılar hem artifact olarak yüklenir hem de istenirse Telegram'a gönderilir. Izgara görseli
geniş olduğu için Telegram'a **dosya olarak** gönderilir; fotoğraf olarak gönderilse Telegram
uzun kenarı ~1280 piksele indirir ve yazılar okunmaz hale gelir.
`CHART_BOT_TOKEN`, `TELEGRAM_CHAT_ID` ve `CHART_TOPIC_ID` depo secret'ı
olarak tanımlanmalıdır.

## Testler

```bash
python -m unittest discover -s tests -t .
```

117 test, hepsi ağsız; sentetik OHLCV serisi üretilir. Gösterge testleri Wilder RMA'sını
elle hesaplanmış değerlerle, Ichimoku kaydırmasını bar sayısıyla, MACD histogramını kimlik
bağıntısıyla, Volume Profile'ı toplam hacmin korunmasıyla ve OBV'yi fiyat yönüyle uyumuyla
doğrular. Kare testleri her ızgara karesinin dört kategoriden birer gösterge taşıdığını, hiçbir
göstergenin tekrar etmediğini, karoların aynı x aralığını paylaştığını ve **mum panelinde
tek gösterge + üç alt panel** kuralının hem tanımda hem üretilen `ChartSpec`'te geçerli
olduğunu kontrol eder. Ayrıca kırpma mantığının panellere gerçekten bağlandığını doğrulayan
testler vardır: `clip_outliers` doğru çalışıp panel onu kullanmazsa kırpma sessizce devre
dışı kalırdı.

---

Bu depo teknik gösterge görselleştirmesi üretir; **yatırım tavsiyesi değildir**.
