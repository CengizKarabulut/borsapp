# ATC 17 Ekim 2026 — GitHub tarafı kaynak paritesi ve teslim kapıları

Orijinal Pine kaynak dosyası **değiştirilmez**: kullanıcı yüklemesi
`Yapıştırılan metin(20261017-210837).txt`, SHA-256
`95bd5849cd9935369fc4928215aeb07f3b2738e526a0bbb435b348cd8a0dae20`.

## Doğrulanan Python düzeltmeleri

- A–I artık yeni `f_native_legacy_snapshot` içindeki **hem yükseliş hem düşüş**
  koşullarını kullanır; önce LONG, sonra SHORT önceliği korunur.
- A–I Stop/TP hesapları Pine'ın aktif *manuel alarm paketindeki* ortak
  swing7 + ATR hesabını kullanır; grafik üzerindeki, ayrı amaçlı `f_plan`
  seviyeleriyle karıştırılmaz. Kullanıcının Pine katsayılarına dokunulmaz.
- Eski 20261014 A–I planları SHA/versiyon gerekçesiyle yayın seviyesine
  taşınmaz. Sadece ilgili değerlendirmeye ait birebir saklanmış OHLCV
  karesinden yeniden hesaplanır.
- Stop/TP fiyatı sıfır veya negatifse raporda `-` kalır; pozitif bir
  işlem fiyatı uydurulmaz.
- Telegram açıklamasında `hisse veri kapsaması` ile
  `18 koşulun hesaplanma kapsaması` birbirinden ayrılır.
- 18. kural için tarihsel MA araştırması, yalnızca
  `ATC_MA_RESEARCH_ON_DEMAND=1` ile gerçek, kapanmış OHLCV üzerinden
  deneysel biçimde açılır. **Varsayılan kapalıdır.** Ölçek testi
  tamamlanmadan canlı gruba gönderim için zorunlu hâle getirilmez.

## Bilerek değiştirilmemiş canlı ayarlar

- Mevcut `ATC_630` sembol evreni korunur. Güncel Pine kaynağında
  631 adet sembol vardır: kaynakta ISATR/ISKUR/UMPAS eklenmiş,
  ALTIN/DMLKT çıkarılmış. 631 sembollük karşılaştırma,
  `config/atc_631_pine_audit_symbols.txt` dosyasında yalnızca denetim
  amaçlı tutulur.
- Üç sağlayıcıdan gelen günlük verilerde ISKUR'un son kaydı
  12 Ağustos 2026; UMPAS ve ISATR için sağlayıcılar çelişmektedir.
  Bu nedenle 631'e doğrudan geçilmemiştir; diğer iki sembolün
  günlük verisi günceldir.
- Pine Rule17'nin **yeni düşüş yönü** henüz sayısal parite testiyle
  doğrulanmış bir Python portuna sahip değildir. İkinci bir yanlı sinyal
  uydurulmaz. Kural 18'in araştırma yolu da deneysel verilerle ölçülmektedir.
- Pine'ın dört zaman dilimli ve iki eşleşmeli manuel bildirim mantığı,
  GitHub'ın sekiz zaman dilimli *tekil koşul eşleşme* Telegram raporuyla
  aynı sonuç sayısı garantisini vermez.

## Doğrulama ve teslim

- `.github/workflows/atc-oct17-readonly-parity.yml` çalışması
  temp PostgreSQL üzerinde gerçek 630 hisse verisini tarar, **Telegram
  göndermez** ve 18 taramanın durumlarını bir CSV'de saklar.
- `.github/workflows/atc-631-provider-probe.yml` yalnızca 5 adet
  farklı sembolün gerçek piyasa sağlayıcı kapsamını denetler.
- Gerçek veri paritesi, uzun süreli MA hesaplama süresi ve Rule17 SHORT
  eşleşmeleri tamamlanmadan **tüm 18 kod / 631 sembol tam parite**
  iddiasında bulunulmaz.
