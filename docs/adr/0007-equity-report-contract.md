# ADR-0007: Hisse araştırma raporu sözleşmesi

Durum: Kabul edildi

## Karar

- `/analiz` tek ekranlık özet, `/rapor` 24 bölümlü A4 PDF üretir.
- İkisi aynı `EquityResearchReport` modelinden türetilir; `/temel` aynı finansal
  provider zincirini kullanır.
- Teknik hesaplar rapor renderer'ında değil, kimlikli
  `research.technical_snapshot` feature'ında yapılır.
- Birincil finansal kaynak `borsapy:public_bist_statements`, alan bazlı fallback
  `yfinance:quarterly_statements` olur. Birincil dolu bir alan fallback ile
  değiştirilmez; her metriğin kaynağı modelde korunur.
- Rapor yalnız kapalı günlük bar üzerinden üretilir. Finansal kolonlar raporun
  `as_of_bar` zamanından sonraysa kullanılmaz.
- Veri yoksa ilgili bölüm `UNKNOWN` olur. Hedef fiyat, yıldız, otomatik AL/SAT
  veya eksik değeri tahmin yoluyla tamamlama yoktur.
- `report_id`; instrument, as-of bar, snapshot/revizyon, feature kimliği ve
  template sürümünden deterministik üretilir. Üretim saati kimliğe girmez.
- PDF artifact kaydı, belge outbox'ı ve komut tamamlanma yanıtı tek PostgreSQL
  transaction'ında tamamlanır.
- GitHub Actions çalışanları geçici olduğundan PDF içeriği outbox payload'ında
  da tutulur. Publisher yerel dosya yoksa bu dayanıklı kopyayı kullanır.

## Bölümler

Yönetici özeti; şirket kartı; yatırım hikâyesi; gelişmeler/KAP; finansal analiz;
finansal sağlık; değerleme; risk; trend; piyasa yapısı; destek/direnç; momentum;
hacim; volatilite; çoklu zaman dilimi; formasyon; Elliott; Fibonacci;
confluence; koşullu senaryolar; kritik seviyeler; teknik özet; birleşik temel +
teknik değerlendirme; güven ve veri kapsamı.

## Sınırlamalar

Bu sürümde doğrulanmış MTF ve Elliott feature'ı yoktur; bu bölümler açıkça
`UNKNOWN` kalır. Genel haber kaynaklarının native porta alınması ile saha parity
kanıtı ayrı göç kapılarıdır.
