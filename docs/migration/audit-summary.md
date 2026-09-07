# İlk legacy denetim özeti

Bu rapor 255 Python dosyası ve toplam 354 kaynak dosya üzerinde üretilmiştir.
Statik analiz karar değil, dosya bazlı migration incelemesinin önceliklendirme
girdisidir.

## Saflık adayları

| Kaynak | PURE | WRAPPABLE | IMPURE |
| --- | ---: | ---: | ---: |
| ma-reaction-scanner | 19 | 8 | 3 |
| market-telegram-suite | 57 | 47 | 11 |
| taramabot | 45 | 31 | 16 |
| tradingview-haber-botu | 4 | 8 | 6 |
| Toplam | 125 | 94 | 36 |

IMPURE sınıfı; ağ, dosya veya teslimat yan etkisi adayı bulunan dosyaları gösterir.
WRAPPABLE sınıfı saat, ortam değişkeni, rastgelelik veya modül seviyesi mutable
state gibi dışarı enjekte edilebilir girdileri gösterir. Test ve yardımcı dosyalar
da tarandığı için sınıf sayıları doğrudan scanner sayısı değildir.

## İndikatör haritası

İsim tabanlı AST taraması 462 tanım/çağrı adayı buldu. En yoğun adaylar:

- RSI: 89
- EMA: 75
- ATR: 62
- MACD: 51
- SMI: 47
- RVOL: 23

Bu sayılar farklı implementasyon sayısı değildir. Sonraki aşamada tanımlar çağrılardan
ayrılacak; formül, parametre, seed ve warmup davranışları elle/parity testiyle
doğrulanacaktır.

## İlk sonuç

- En temiz başlangıç MA motorunda görünüyor.
- Taramabot içinde veri, saat, ortam ve teslimat sorumluluklarının ayrıştırılması daha yoğun.
- Haber botunda I/O doğal olarak yüksek; news ingestion sınırı olarak ele alınmalı,
  scanner saflık ölçütüyle doğrudan değerlendirilmemeli.
- Telegram dosyaları merkezi listener/publisher/outbox altında birleşme adayıdır.

Sonraki karar çıktıları legacy alias tablosu, scanner giriş noktaları ve gerçek
indikatör implementasyon kümeleridir.
