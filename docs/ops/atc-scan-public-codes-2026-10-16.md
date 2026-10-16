# ATC Telegram tarama sunumu — kısa kod ve kanıtlanan yön

Bu değişiklik **yalnızca dışarıya gösterilen raporların biçimini** değiştirir.
Özgün 18 taramanın kuralları, eşleşme testleri, orijinal veri sağlayıcı
kanıtları, pozisyon planları, fiyatlar ve kapanış kontrolleri değiştirilmez.

## Kısa kod sözleşmesi

Kullanıcının 16 Ekim 2026 Pine kaynak kodundaki `A-I` işaretleri birebir
1–9 numaralı kuralları ifade eder. 10–18 numaralı kurallar doğrudan
`10,11,12,13,14,15,16,17,18` kodlarıyla gösterilir. Kod–motor eşleşmesinin
tek kaynağı `src/market_intelligence/scanning/display_codes.py`'dir.

Yön kodu yalnızca **aynı değerlendirmeye ait kalıcı `scan_events` veya
`active_states` yön kanıtından** alınır:
- `LONG` yalnız teyitli `bullish` olduğunda.
- `SHORT` yalnız teyitli `bearish` olduğunda.
- `NÖTR` yalnız `neutral` olduğunda.
- `KARMA` eşzamanlı veya karışık yön kanıtları olduğunda.
- `?` eşleşme var ama güvenilir yön kanıtı saklanmamışsa.

Bir taramanın adı, teknik göstergesi veya eski strateji eğilimi kullanılarak
yön **tahmin edilmez**. `NÖTR` ve `KARMA` kayıtlar yanlışlıkla
LONG/SHORT sayılmaz, Kesişim oylarına dahil edilmez.

## Dışa açık raporlar

- Her zaman diliminin 20 satırlık PNG kartları: **HİSSE | KOD | YÖN**.
- Tam teyitli CSV: **Hisse | TaramaKodu | Yon | TeyitliMumTSI**.
- Gün içi geçici PNG ve CSV: aynı kod/yön düzeni; `CANLI/TEYİTSİZ`
  ve zaman damgası korunur. Kanıtlanmamış yön `?` olarak görünür.
- Çoklu zaman Kesişim PNG ve CSV: yalnız hisse, LONG/SHORT,
  zaman dilimleri ve **kodlar**. Formül adı/teknik özellik listesi yok.
- Eski genel tarama özeti üretilebiliyorsa sadece kod ve eşleşme sayısı
  gösterir; özet veri kaynağında yön kanıtı yoksa LONG/SHORT uydurmaz.
- Motor denetimi ve dahili veri kaynakları aynı kalır; dış ekranlarda
  yöntem detayları yayımlanmaz.

Sunum amaçlı örnekler (gerçek sinyal değildir):
`#ASELS · A · LONG`, `#THYAO · 13 · SHORT`,
`#BIMAS · 10 · NÖTR`, `#TUPRS · 18 · KARMA`.

Eski Telegram mesajları silinmez veya geriye dönük düzenlenmez.
Yeni yayınlar bu sözleşmeyle gönderilir.
