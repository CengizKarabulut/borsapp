# Uygulama durum kaydı

Bu dosya plan belgelerindeki 14 açığın kod karşılığını izler. `Tamamlandı`,
yalnız test edilebilir çıktı bulunduğunda kullanılır; tablo bir parity kanıtı
yerine geçmez.

| Açık | Durum | Kanıt / sıradaki iş |
| --- | --- | --- |
| G-01 Shadow parity | Kısmi | 18 scanner için gerçek legacy adapter, store, rapor ve gate hazır; MA Research parity ve saha kanıtı eksik |
| G-02 Teslimat modu | Tamamlandı | `SCAN_DELIVERY_MODE`, varsayılan `shadow`, CLI `--notify` kilidi |
| G-03 Docker context | Tamamlandı | Gerekli iki vendor ağacı image context'ine dahil; CI image build işi var |
| G-04 Migration runner | Tamamlandı | `db-migrate`, `db-version`, checksum ve dry-run |
| G-05 Teknik/research legacy bağı | Kısmi | `/analiz`, `/rapor`, `/temel` canonical servis + outbox üzerinde; yalnız grafik renderer compatibility katmanında |
| G-06 Genel haber legacy bağı | Açık | Canonical KAP hazır; genel haber legacy modül adapterini kullanıyor |
| G-07 KARAR ailesi | Tamamlandı | `decision.panel_v645`, günlük 252-bar warmup, golden legacy testi ve shadow adapter hazır |
| G-08 PostgreSQL entegrasyon | Tamamlandı | PostgreSQL 16 CI service ve migration idempotency testi |
| G-09 Kullanılmayan tablolar | Kısmi | `canonical_bars` 002 ile düşüyor; outcomes kullanılıyor, corporate action ingestion bekliyor |
| G-10 Kalıcı host | Açık | Compose tanımlı; host seçimi ve gerçek dağıtım kullanıcı kararı gerektirir |
| G-11 Gözlemlenebilirlik | Kısmi | `doctor` ve runtime healthcheck hazır; yapılandırılmış log/uyarı politikası bekliyor |
| G-12 CI kapsamı | Kısmi | 3.11/3.12 unit, image ve PostgreSQL işleri var; type/security kontrolleri bekliyor |
| G-13 Hijyen | Tamamlandı | Dürüst README, LICENSE, NOTICE, env örneği ve migration map |
| G-14 Outcome ölçümü | Tamamlandı | Yön-duyarlı 5/10/20 bar MFE/MAE, XU100 excess return, idempotent backfill, rapor CLI ve workflow |

## Araştırma komutları

- `/analiz`: canonical günlük frame + ortak feature + finansal provider zincirinden
  tek ekran özet; merkezi outbox.
- `/rapor`: aynı modelin 24 bölümlü PDF görünümü; deterministik rapor kimliği,
  `research_artifacts` kaydı ve dayanıklı `sendDocument` outbox payload'ı.
- `/temel`: BIST kamu finansal tabloları birincil, yfinance alan bazlı fallback;
  kaynak/kapsam görünür ve eksik alanlar `UNKNOWN`.
- OHLCV kullanan ingestion yolları borsapy birincil, yfinance fallback olacak
  şekilde tek provider zincirinden geçer.

## Bu dilimde eklenen scanner kapsamı

- SIGNAL: 9
- TECHNICAL: 7 (`sikisma_hacim`, `hacim_patlamasi`, `asiri_bolge`,
  `basarisiz_kirilim`, `karar_bolgesi`, `trend_devami`, `tukenme`)
- MA: 1
- KARAR: 1
- Toplam: 18

Canlı bildirim kapsamı, scanner'ın katalogda bulunmasından ayrıdır. Parity gate
tamamlanıncaya kadar bir scanner'ın çalışması onun legacy ile doğrulandığı
anlamına gelmez.
