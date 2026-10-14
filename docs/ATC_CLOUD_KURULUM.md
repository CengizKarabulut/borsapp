# ATC tamamen bulut — GitHub Actions üzerinden PC gerektirmeyen işletim

## Mevcut duruma ilişkin önemli gerçekler

- Tarama, veri alma, veri doğrulama ve Telegram gönderme işlerinin tamamı GitHub-hosted runner üzerinde gerçekleştirilebilir; **yerel bilgisayar açık kalmaz**.
- GitHub Actions işi bittiğinde runner silinir. Kalıcı scanner geçmişi / outbox **PostgreSQL DATABASE_URL** aracılığıyla GitHub dışındaki kalıcı veritabanında tutulur. GitHub tek başına kalıcı PostgreSQL servisi sağlamaz.
- BIST fiyat geçmişi borsapy / yfinance vb. dış sağlayıcılardan, Telegram teslimatı Telegram API'den gelir. “Tamamen GitHub” burada yürütme ve kaynak kodu tek merkezden yönetme anlamındadır, bütün hizmetlerin GitHub içinde barınması değildir.
- 2026-10-14 başarılı `universe-sync` iş günlüğünde **BIST_ALL = 582** görülmüştür. Eski ATC Excel hedef evreni **630** olduğu için fark **48**'dir. Kaynaklar eşlenmeden 630 hisse tarandı iddiası yapılamaz.

## İş akışları

| GitHub Actions | İşlev | Etkinleştirme |
| --- | --- | --- |
| `universe-sync.yml` | BIST evrenini PostgreSQL'e eşitler | Mevcutta zamanlanmış |
| `scheduled-scan.yml` | Mevcut Python 18 scanner / teyitli mumlar | `ENABLE_SCHEDULED_SCANS=true` |
| `ma-research.yml` | 18. scanner'ın gerekli MA kalite geçmişi | `ENABLE_SCHEDULED_RESEARCH=true` |
| `telegram-pulse.yml` | Mevcut outbox gönderimleri ve bot komutları | `ENABLE_TELEGRAM_PULSE=true` |
| `atc-cloud-report.yml` (yeni) | PostgreSQL → tam ATC tarama matrisi; günlük rapor | `ENABLE_ATC_CLOUD_REPORT=true` |
| `kap-news.yml` | KAP haberleri | `ENABLE_SCHEDULED_NEWS=true` |

Yeni workflow her hafta içi yaklaşık **19:45 TSİ** son kapanış raporunu hazırlar. GitHub zamanlayıcısı garanti edilen tam dakikada çalışmayabilir. Raporlarda en az %95 güncel, kapanmış günlük mum kapsaması zorunludur. Eski veya eksik veri başarılı tarama gibi gösterilmez. Evren sayısı 630'dan azsa dışa aktarım raporu hata verir.

**Bu PR merge edilmeden zamanlanmış yeni workflow ana dalda görünmez veya tetiklenmez.** Ana dal güvenlik açısından şimdilik değiştirilmemiştir.

## Sadece bir kez GitHub web arayüzünde yapılacak ayarlar

Repository > Settings > Secrets and variables > Actions:

### Secrets
- `DATABASE_URL`: sürdürülebilir PostgreSQL hizmetinin bağlantı adresi
- `TELEGRAM_BOT_TOKEN`: Telegram botu
- `TELEGRAM_CHAT_ID`: hedef Telegram forum/süpergrup

Bu değerleri sohbete veya Git'e yazmayın. Zaten tanımlılarsa yeniden oluşturmayın.

### Variables — kontrollü açma sırası
1. `ATC_REQUIRED_MEMBERS=630` hedefini koruyup eksik 48 sembolü denetleyin.
2. `ENABLE_SCHEDULED_SCANS=true` (önce küçük manuel scan pilotu ve veri sağlayıcı limitleri doğrulandıktan sonra).
3. `ENABLE_SCHEDULED_RESEARCH=true` (MA araştırmasının kaynak tüketimini test ettikten sonra).
4. `ENABLE_ATC_CLOUD_REPORT=true` (gerçek değerlendirme kayıtları mevcutsa).
5. `ATC_REPORT_DELIVERY_MODE=shadow` (ilk birkaç gün mesaj göndermeden test).
6. `ATC_REPORT_DELIVERY_MODE=live` ve `ENABLE_ATC_REPORT_NOTIFICATIONS=true` (kontroller geçince yeni günlük rapor **Raporlar** konusuna gider).
7. `ENABLE_TELEGRAM_PULSE=true` (gruptaki komutlar ve diğer outbox bildirimleri için).
8. Mevcut bireysel tarama bildirimleri için ayrıca `SCAN_DELIVERY_MODE=live` gerekir. Doğrulanmamış scanner timeframelerini otomatik canlı açmayın.

### Gizlilik

`borsapp` deposu kamusaldır. `ATC_SHARE_CSV_ARTIFACT` değişkenini **true yapmayın**; bu, tarama sonuçlarını GitHub Actions artifact olarak repo okuyucularına açabilir. Yeni workflow bu yüklemeyi varsayılan olarak kapalı tutar. Gizli analizlerin paylaşılacağı yer hedef özel Telegram grubu + kalıcı DB olmalıdır. Herkese açık GitHub Pages sitesi otomatik kurulmaz.

## GitHub üzerinde nasıl test edilir?

1. PR birleştirildikten sonra Actions > **ATC cloud dashboard and Telegram report** > **Run workflow** ile ilk kontrolü manuel başlatın. `notify=false` bırakın.
2. İş, evreni 630 olarak bulmazsa açık hata verecektir; bunun giderilmesi gerekir. Yanlışlıkla 582 hisseye ait rapor gönderilmez.
3. 630 düzeltildikten sonra veri toplayıp taramalar gerçekten sonuç ürettiğinde rapor, en az %95 güncel günlük mum varsa devam eder.
4. Daha sonra varsayılanı `shadow` olan Telegram bildirimlerini ve `SCAN_DELIVERY_MODE` ayarlarını kontrollü açın.

## Sınırlar

- GitHub Actions beklemeleri/gecikmeleri olabilir; gerçek zamanlı websocket servisi değildir.
- Kaynak verilerin lisans/erişim hızı, GitHub'nin CI kotası ve üçüncü taraf DB kapasitesi bağımsız sınırdır.
- Tüm 18 tarama için Pine/Python sayısal parite doğrulanmadan otomatik **yatırım amaçlı sinyal** yayını açılmamalı.
- Excel/Power BI masaüstü uygulamaları sunucu değildir. Mevcut CSV çıktısı özel cihaz olmadan GitHub üzerinde üretilebilir; fakat gerçek zamanlı etkileşimli, özel erişimli web paneli ayrı ve kontrollü bir dağıtım adımıdır.
