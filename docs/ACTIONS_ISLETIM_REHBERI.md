# GitHub Actions: grup raporları ve bakım işleri

Güncelleme: 23.10.2026. Güncel grup raporları kalıcı PostgreSQL kullanmaz.
Eski deneme ve kurtarma workflow'ları kaldırıldı; uygulama modülleri, geçmiş
sonuçlar ve E diskindeki araştırma dosyaları bu temizlikte değiştirilmedi.

## Grupta kullanılan dört iş

| Actions adı / dosya | Ne yapar? | Çalıştırma |
| --- | --- | --- |
| ATC automatic latest candle snapshots — `atc-scheduled-snapshots.yml` | 630 hissenin 18 taramasını sekiz zaman diliminde değerlendirir; aynı zaman dilimi ve zaman dilimleri arası kesişimleri mevcut konulara yollar | Otomatik; elle `scope=due` veya `all` |
| ATC 630 morning support resistance and pivot report — `atc-ephemeral-morning.yml` | Önceki kapanmış seansa ait Traditional P/S1–S3/R1–R3; 630 hisse, 32 görsel sayfa ve tam CSV | Hafta içi 08:35 TSİ; elle de çalışır |
| ATC manual live candle snapshot — `atc-live-snapshot.yml` | Seçilen tek zaman diliminin güncel mumunu değerlendirir | Elle; önce `delivery=preview`, gruba göndermek için `publish` |
| ATC manual support resistance and pivot report — `atc-support-pivot-report.yml` | Sabah raporuyla aynı hesaplamayı istenen zamanda üretir | Elle; önce `preview`, sonra `publish` |

Actions → istenen iş → **Run workflow** → **Branch: main**.
`preview` yalnız dosya hazırlar; `publish` Telegram'a gönderir.
Otomatik işte elle başlatılan çalışmanın varsayılanı da `preview` olur.
Saatleri değiştirmek için [tarama takvimi](ATC_AUTOMATIC_SCHEDULE.md) esas alınır.
GitHub zamanlayıcısı gecikebilir; tam dakikasında teslim garantisi yoktur.

Son açık mum kullanılır; fiyat ve koşullar mum kapanmadan değişebilir.
Görseller yön bildirim politikasına göre ayrılır; her grubun en güçlü en çok
20 hissesi gösterilir. Sıralama sağlanan bağımsız koşul sayısına dayanır,
başarı olasılığı değildir. Tam tarama matrisi CSV'de kalır. BIST SHORT
bildirimlerinin kapatılması düşüş analizinin hesaplardan silinmesi anlamına gelmez.
Destek/direnç raporunda 20 sınırı hisse kapsamını azaltmaz: her sayfa en çok
20 satır içerir ve 630 hissenin tümü görsellerde yer alır.

Güncel raporların gerekleri: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
mevcut zaman dilimi topic yönlendirmeleri ve `TELEGRAM_TOPIC_REPORTS`.
`DATABASE_URL` veya `ENABLE_SCHEDULED_SCANS` gibi eski değişkenler bu dört
işin açma/kapama düğmesi değildir. Emir gönderimi bu işlerin parçası değildir.

## Bakım için kalan işler

Bu işler yalnız **Run workflow** ile başlatılır; gruba düzenli rapor göndermez.
İsimleri Actions ekranında **Maintenance** ile başlar.

| Dosya | Amaç / gereklilik |
| --- | --- |
| `atc-universe-drift-audit.yml` | Sabit 630 liste ile sağlayıcının güncel BIST listesini karşılaştırır; listeyi kendiliğinden değiştirmez |
| `atc-existing-topics-audit.yml` | Mevcut Telegram konu yönlendirmesini kontrol eder; mesaj göndermez |
| `atc-read-only-topic-discovery.yml` | Telegram'ın mevcut konu metadatasını okur; güncelleme kuyruğunu tüketmez |
| `atc-db-storage-diagnostic.yml` | Eski PostgreSQL kapasitesini yalnız okur |
| `atc-storage-breakdown-readonly.yml` | Eski OHLCV veritabanındaki tablo/index kullanımını okur |
| `atc-telegram-visual-diagnostics.yml` | Eski veritabanı outbox teslim kayıtlarını okur; güncel RAM raporlarının teslim defteri değildir |
| `operations-diagnostics.yml` | Eski veritabanı komut kuyruğunu inceler |
| `universe-sync.yml` | İsteğe bağlı yerel/kalıcı PostgreSQL evrenini günceller; RAM 630 listesini değiştirmez |
| `ma-research.yml` | İsteğe bağlı PostgreSQL MA araştırması; E'deki 2.524 Stop/TP araştırmasını başlatmaz veya takip etmez |
| `outcomes.yml` | PostgreSQL'de birikmiş teyitli bulguların geçmiş sonuçlarını ölçer |
| `kap-news.yml` | PostgreSQL'e KAP/haber eşitler; yalnız `notify=true` ve canlı teslim ayarıyla bildirim kuyruğu oluşturur |
| `telegram-pulse.yml` | PostgreSQL komut dinleyicisini sınırlı süre çalıştırır ve outbox yayınlar; sürekli bot sunucusu değildir |

Veritabanına bağlı işlerin eski otomatik takvimleri kaldırıldı. Son kontrolde
ilgili açma değişkenleri zaten kapalıydı; evren eşitlemesinin korumasız günlük
tetiklemesi de kaldırıldı. Kapasitesi dolmuş eski veritabanını tekrar düzenli
yazmaya açmak grup raporlarını iyileştirmez. Haber/finansal botu düzenli
çalıştırmak için önce kalıcı veritabanı kapasitesi, tek dinleyici ve yayın
kuyruğu ayrıca doğrulanmalıdır.

**CI** kod gönderimlerinde ve pull request'lerde test/lint, Docker ve
PostgreSQL entegrasyon kontrollerini çalıştırmaya devam eder.

## Kaldırılan eski girişler

45 YAML workflow 17'ye indirildi. Aşağıdaki 28 dosya yalnız workflow
girişleriydi; kaynak uygulama ve analiz algoritmaları silinmedi. Önceki
sürümler Git geçmişinden alınabilir.

| Tür | Kaldırılan dosyalar (`.yml`) | Güncel karşılık |
| --- | --- | --- |
| Eski DB taraması ve yayın denemeleri | `scheduled-scan`, `atc-630-daily`, `atc-cloud-report`, `atc-confirmed-intersections`, `atc-ephemeral-six-scans`, `atc-ephemeral-preview`, `atc-live-hourly-pilot`, `atc-live-daily-publish-pilot`, `atc-live-preview-recovery`, `atc-telegram-briefings`, `atc-manual-operations` | Dört güncel grup işi |
| Tarihli tek seferlik tarama / risk kanıtı | `atc-631-provider-probe`, `atc-oct17-readonly-parity`, `atc-oct17-risk-gate-dryrun`, `atc-oct17-weekly-readonly`, `atc-one-shot-daily-weekly-audited`, `atc-real-ohlc-diagnosis`, `atc-real-risk-diagnostics` | Güncel preview ve CI; eski kanıt Git/Actions geçmişinde |
| Eski DB eksik-veri ve önizleme teşhisi | `atc-live-coverage-diagnostic`, `atc-preview-source-probe`, `atc-preview-trace-diagnostic`, `atc-problem-diagnostics`, `atc-seed-missing-timeframes`, `atc-stop-overquota-seed` | Güncel rapordaki kaynak/kapsam alanları; salt okunur bakım işleri |
| Tek seferlik topic müdahaleleri / mesaj testleri | `atc-repurpose-four-topics`, `atc-quarantine-rejected-topic`, `atc-telegram-topic-photo-smoke`, `telegram-smoke` | Mevcut konu audit işleri; konu değiştirme veya test mesajı otomatik yapılmaz |

Bazı eski kurulum ve olay notları bu dosya adlarını tarihsel kanıt olarak
anabilir. Bu notlar güncel etkinleştirme talimatı değildir.
`_legacy/` altındaki modüllerin bir bölümü hâlâ compatibility adapterleri ve
parite testleri tarafından kullanılır; topluca silinmedi.
