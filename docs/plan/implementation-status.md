# Uygulama durum kaydı

Bu dosya plan belgelerindeki 14 açığın kod karşılığını izler. `Tamamlandı`,
yalnız test edilebilir çıktı bulunduğunda kullanılır; tablo bir parity kanıtı
yerine geçmez.

| Açık | Durum | Kanıt / sıradaki iş |
| --- | --- | --- |
| G-01 Shadow parity | Açık | Karşılaştırma sözleşmesi var; gerçek legacy adapter, store, rapor ve gate eksik |
| G-02 Teslimat modu | Tamamlandı | `SCAN_DELIVERY_MODE`, varsayılan `shadow`, CLI `--notify` kilidi |
| G-03 Docker context | Tamamlandı | Gerekli iki vendor ağacı image context'ine dahil; CI image build işi var |
| G-04 Migration runner | Tamamlandı | `db-migrate`, `db-version`, checksum ve dry-run |
| G-05 Teknik/research legacy bağı | Kısmi | 7 TECHNICAL scanner taşındı; grafik/araştırma compatibility katmanı kaldı |
| G-06 Genel haber legacy bağı | Açık | Canonical KAP hazır; genel haber legacy modül adapterini kullanıyor |
| G-07 KARAR ailesi | Açık | `decision.panel_v645` canonical scanner'a taşınacak |
| G-08 PostgreSQL entegrasyon | Tamamlandı | PostgreSQL 16 CI service ve migration idempotency testi |
| G-09 Kullanılmayan tablolar | Kısmi | `canonical_bars` 002 ile düşüyor; corporate actions/outcomes bekliyor |
| G-10 Kalıcı host | Açık | Compose tanımlı; host seçimi ve gerçek dağıtım kullanıcı kararı gerektirir |
| G-11 Gözlemlenebilirlik | Açık | `doctor`, yapılandırılmış log ve runtime healthcheck eklenecek |
| G-12 CI kapsamı | Kısmi | 3.11/3.12 unit, image ve PostgreSQL işleri var; type/security kontrolleri bekliyor |
| G-13 Hijyen | Tamamlandı | Dürüst README, LICENSE, NOTICE, env örneği ve migration map |
| G-14 Outcome ölçümü | Açık | Şema var; backfill/report uygulaması yok |

## Bu dilimde eklenen scanner kapsamı

- SIGNAL: 9
- TECHNICAL: 7 (`sikisma_hacim`, `hacim_patlamasi`, `asiri_bolge`,
  `basarisiz_kirilim`, `karar_bolgesi`, `trend_devami`, `tukenme`)
- MA: 1
- Toplam: 17

Canlı bildirim kapsamı, scanner'ın katalogda bulunmasından ayrıdır. Parity gate
tamamlanıncaya kadar bir scanner'ın çalışması onun legacy ile doğrulandığı
anlamına gelmez.
