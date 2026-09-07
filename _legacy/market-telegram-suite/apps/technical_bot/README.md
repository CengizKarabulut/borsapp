# Technical / Research Telegram Bot

Bu uygulama BIST için teknik durum, temel analiz, tarama ve bütünleşik hisse
araştırması üretir. Çıktılar deterministiktir; otomatik AL/SAT çağrısı değildir.

## Telegram hedefi

Hedef hiçbir dosyada sabit bir grup veya topic numarasına bağlanmaz. GitHub
Actions secrets kullanılır:

- `TECHNICAL_BOT_TOKEN` → workflow içinde `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` → forum grubu
- `TECHNICAL_TOPIC_ID` → teknik/araştırma forum konusu
- `TELEGRAM_ALLOWED_USERS` → isteğe bağlı komut yetkilendirmesi

Bu uygulama başka repodaki Telethon/session altyapısını kullanmaz.

## Komutlar

- `/analiz ASELS` — bütünleşik araştırma paketi
- `/rapor ASELS` — `/analiz` ile aynı güncel paket; eski teknik rapor motoru yoktur
- `/temel GARAN` — sektör uyarlamalı temel analiz + radar kartı
- `/tara [aralık]` — BIST taraması
- `/liste` — son tamamlanan taramanın listesi
- `/takip THYAO [aralık]` — teyitli yapısal seviyeleri izler
- `/takip sil THYAO` — takipten çıkarır
- `/esik ...` — tarama eşik ayarları
- `/durum` — bot/tarama durumu
- `/gecmis [no]` — saklanan tarama artifact'leri

## `/takip` seviye mantığı

Takip sistemi, son teyitli swing high/low değerlerini körlemesine alt/üst eşik
olarak kaydetmez. Önce seçilen zaman dilimindeki **son tamamlanmış mum kapanışı**
referans alınır. Ardından 5 sol + 5 sağ mumla teyit edilmiş swing pivotları
fiyatın iki yanına ayrılır:

- referans kapanışın altındaki en yakın teyitli yapı → **alt eşik**;
- referans kapanışın üstündeki en yakın teyitli yapı → **üst eşik**.

Bu nedenle fiyat örneğin 21 TL iken daha önce kırılmış 27,98 TL swing dip artık
“alt eşik” olamaz. Fiyatın üzerinde kaldığı için rol değiştirmiş bir
**reclaim/yukarı izleme seviyesi** olarak sınıflanabilir.

Zorunlu invariant:

```text
alt eşik < son teyitli kapanış < üst eşik
```

Bu koşul sağlanmazsa takip oluşturulmaz. Bir tarafta yeterli teyitli swing yoksa
son 20 tamamlanmış barın fiyat sınırı yalnız yedek seviye olarak kullanılabilir;
iki taraf da üretilemiyorsa sistem tahmin yürütmez ve takip kaydını reddeder.

Alarm kontrolü canlı/tamamlanmamış mumun o anki fiyatıyla yapılmaz. `1h`, `4h`,
`1d`, `1wk`, `1mo` gibi hangi aralık seçildiyse yalnız o aralığın **tamamlanmış
mumu** yeni bir kapanış oluşturduğunda kontrol edilir. Mevcut eski watchlist
kayıtlarında referans bilgisi yoksa sistem onları doğrudan tetiklemek yerine
önce yeni kurallarla otomatik yeniden hesaplar.

## `/analiz` araştırma paketi

Tek komut dört görsel üretir:

1. Araştırma özeti
2. Temel analiz radar kartı
3. Günlük hareketli ortalama tablosu
4. 16:9 çok panelli teknik grafik

Araştırma özeti beş bağımsız boyutu gösterir:

- **Şirket Kalitesi:** değerleme hariç sektör uyarlamalı büyüme, kârlılık,
  bilanço/sermaye ve nakit kalitesi.
- **Bilanço Trendi:** mümkün olduğunda son 8 çeyrek + TTM.
- **Kâr Kalitesi:** CFO/net kâr, FCF, accrual ve işletme sermayesi ayrışmaları.
- **Değerleme:** şirket kalitesinden ayrı, sektör-eşi veya BIST-geneli göreli
  çarpan konumu.
- **Teknik Yapı:** teyitli swing yapısı, momentum/katılım, AlphaTrend ve
  günlük/haftalık/aylık bağlam.

Genel araştırma kapsamı, bu boyutların gerçek veri kapsamından hesaplanır.
Eksik veri otomatik olumsuz veya nötr puana çevrilmez.

## Temel analiz profilleri

### Banka

Kart başlıkları:

- Gelir / Gider Yapısı
- Büyüme
- Kârlılık
- Sermaye Gücü
- Bilanço Yapısı

`Sermaye Gücü`, resmi BDDK SYR değildir. Resmi SYR/NPL/karşılık verisi güvenilir
kaynakta yoksa sistem bunları tahmin etmez.

### GYO

NAV/portföy ekspertiz verisi sağlayıcıda bulunmuyorsa bu eksiklik açıkça
belirtilir. PD/DD ve mevcut finansal metriklerle sınırlı değerleme yapılır;
NAV varmış gibi davranılmaz.

### Genel şirket

Büyüme, kârlılık, bilanço, nakit dönüşümü ve göreli çarpanlar birlikte okunur.
Muhasebe kârı ile nakit üretimi ayrı değerlendirilir.

## Hareketli ortalama tablosu

Günlük SMA:

- Kısa vade: `5 / 8 / 13`
- Orta vade: `21 / 34 / 55`
- Uzun vade: `89 / 144 / 233`

Her satırda değer, fiyatın ortalamaya göre konumu ve 3 günlük MA eğimi vardır.
Her grup için pozitif / karışık / negatif dizilim özeti gösterilir. Yeni halka
arz gibi yeterli geçmişi olmayan hisselerde uzun MA uydurulmaz; `VERİ YETERSİZ`
yazılır.

## 16:9 teknik grafik

Ana panel:

- OHLC mumları
- Bollinger Bands `(20, 2)`
- AlphaTrend `(14, 1)`
- teyitli `HH / HL / LH / LL`
- `BOS / CHoCH`
- aktif destek/direnç bölgeleri ve seviye kalite kanıtları

Alt paneller:

- Hacim + 20 günlük ortalama
- MACD `12/26/9 EMA`
- SMI `10/3/3`
- RSI `14` + SMA14 + regular divergence `(5/5, 5–60)`
- OBV
- ATR `14 RMA`

Gösterge hesap katmanı kullanıcı tarafından sağlanan TradingView/Pine
formüllerini esas alır. RSI hidden divergence mantığı kodda bulunabilir fakat
varsayılan görünümde kapalıdır. AlphaTrend'in BUY/SELL koşulları hesaplanır fakat
ürün tercihi gereği BUY/SELL etiketleri rapora basılmaz.

Fiyat Bollinger kodu ayrıca verilmediği için fiyat panelinde standart TradingView
`SMA20 ± 2σ` kullanılır.

## Teknik yapı ve seviyeler

Teyitli pivotlarda sağ taraf mumları tamamlanmadan swing kesinleşmiş sayılmaz.
Seviyeler pivot, EMA, yaklaşık POC ve anlamlı swinglerde Fibonacci confluence
kaynaklarından kümelenir. Her bölge için temas, güncellik, reaksiyon gücü,
confluence ve ATR uzaklığı değerlendirilir.

Kurallar:

- destek güncel fiyatın altında olmak zorundadır;
- direnç güncel fiyatın üstünde olmak zorundadır;
- kırılan seviye rol değiştirebilir;
- 6 ATR'den uzak veya aşırı eski bölge aksiyon seviyesi olarak gösterilmez;
- Elliott kesin 1–5 etiketi zorlamaz, `primary / alternate / confidence /
  invalidation` bağlamı üretir ve yeterli swing yoksa `BELİRSİZ` kalır.

## Risk

Risk aileleri yalnız mevcut kanıt varsa sıralanır:

- finansal kaldıraç / banka bilanço vekilleri
- kâr kalitesi
- değerleme hassasiyeti
- teknik yapı
- likidite

Veri yoksa `50/100` gibi yapay bir risk yaratılmaz. Ana risk yalnız ölçülebilir
kanıta dayanır; düşük riskli bir tabloda zorla “yüksek ana risk” seçilmez.

## Veri sınırları

BIST OHLCV verisi varsayılan olarak borsapy/TradingView yolundan gelir. Veri
sağlayıcı kısıtları, gecikme ve dönem kapsamı rapor yorumunda dikkate alınmalıdır.
Gerçek footprint/order-flow olmadığı halde OHLCV proxy değerleri gerçek delta
gibi sunulmaz.

Temel veride bulunmayan resmi banka oranları, GYO NAV veya ileriye dönük analist
konsensüsü tahmin edilmez.

## Workflow ve test

Üretim taraması `technical-scan.yml` içinde tekrar tüm unit testleri çalıştırmaz;
kod kalitesi ve testler PR/push sırasında merkezi `ci.yml` tarafından yürütülür.
Canlı veriyle bütünleşik kalite kontrolü `research-report-smoke.yml` üzerinden
GARAN/ZGYO/ASELS için yapılır. Güncel paketin manuel Telegram doğrulaması
`research-telegram-send.yml` ile yapılabilir.

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
ruff check src tests
python -m unittest discover -s tests -v
```
