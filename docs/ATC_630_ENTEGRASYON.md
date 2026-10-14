# ATC 630 hisse / 18 tarama entegrasyonu — Aşama 1

**Referans:** Kullanıcının paylaştığı `ATC TV200 20 Grup Live v20261012 [Izleme]` Pine v6 taslağı. Pine, 1–18 koşul hesaplarını ve 20 × 10 TradingView izleme grubu içeriyor. Bu 200 hisse grubu **borsapp'ın Python evreni değildir**. Python motorundaki 18 scanner `config/scanners.toml` ve `market_intelligence/scanning/` altında bulunuyor.

## Eklenen

- `scripts/atc_export_dashboard.py`: PostgreSQL'de **gerçekten kaydedilmiş** tarama değerlendirmelerini, Excel / Power Query / Power BI tarafından okunabilir `ATC_Tarama_Matris.csv` dosyasına dönüştürür. Veritabanında değişiklik yapmaz.
- Hisse evrenini `PostgresRuntimeRepository.list_universe(..., as_of=...)` üzerinden alır, 630 değerini hardcode etmez. Gerçek sayı konsol özetinde gösterilir.
- 18 × 6 × evrendeki hisse sayısı kadar durum oluşturur. Hücrelerin mevcut olması, taramaların hepsinin çalıştığı anlamına gelmez.
- Durumlar: `POZITIF`, `NEGATIF`, `NOTR`, `KARMA`, `KOSUL_YOK`, `HESAPLANAMADI`, `VERI_YOK`, `DESTEKLENMIYOR`, `SURUM_UYUSMAZLIGI`, `ESLESME_YON_BELIRSIZ`.
- Yönü olay tablosunda kayıtlı olmayan state türü eşleşmeler yanlışlıkla pozitif/negatif sayılmaz. Yönün güvenilir saklanması sonraki aşamadır.
- `MumKapanisiUTC` ve `KuralHash` hem eski veriyi hem de hesaplama sürümü uyuşmazlıklarını ayırt etmek için sunulur.

## Yerel çalışma

Python 3.11+, PostgreSQL ve `DATABASE_URL` bağlantısı gerekir. BIST evreni ve tarama sonuçları önceden üretilmiş olmalıdır.

```powershell
python -m pip install -e '.[runtime]'
python scripts/atc_export_dashboard.py --universe BIST_ALL --output runtime_artifacts/ATC_Tarama_Matris.csv
```

Çıkan CSV'yi Excel'in Power Query aracı üzerinden içe alıp yenileyebilirsiniz. Raporlama ile analiz aynı **borsapp** veri kaynağına dayanır. Bu komut piyasadan yeni OHLCV toplamaz; henüz hesaplanmamış tarama sonucu üretmez.

## Mevcut Telegram yönlendirmeleri

`TELEGRAM_CHAT_ID` ortak hedef gruptur. `TopicRouter` üzerinden `SCAN_EVENT` / `CONFLUENCE` → `TELEGRAM_TOPIC_SCANS`, `REPORT` → `TELEGRAM_TOPIC_REPORTS`, `ANALYSIS` → `TELEGRAM_TOPIC_ANALYSIS`, `SYSTEM` → `TELEGRAM_TOPIC_SYSTEM` olarak yönlendirilir. Tek bot ve tek publisher yeterli.

**Bu ilk aşama, canlı Telegram gönderimlerini veya mevcut `notification_timeframes` izinlerini değiştirmiyor.** Mevcut 18 scanner'ın tamamı için Pine/Python sayısal parite doğrulanmadığından sessizce bildirim açmak güvenli değildir.

## Sonraki adımlar

1. 630 sembol eşleşmesi ile 18 motorun çıktı/veri kapsamı denetimi.
2. Aynı fiyat bazında teyitli OHLCV ile 1h/4h/1d/1wk tarama testleri. 17 yalnız 1d, 18 ise uzun geçmiş ve nitelikli MA araştırması gerektirir; 5m mevcut shadow listesinde desteklenmez.
3. Pine 1–9 **görsel** koşulları ile aynı dosyanın **native packet** hesaplarını karıştırmadan sayısal parite karşılaştırması. Pine dosyası kendi içinde derleme/feed eşitliğinin henüz doğrulanmadığını belirtiyor.
4. State bulgularında yön bilgisi ve planlar için sürüm-zaman damgası korunarak kalıcı kayıt.
5. Tekrarlı raporların outbox semantic key ile engellendiği bir **shadow Telegram pilotu**, ardından kullanıcı onayıyla canlı konu bildirimleri.

Ardından ATC Excel ekranındaki `VERI_YOK` / `KOSUL_YOK` ayrımı gerçek kaydedilmiş değerlendirmelerden gelir.
