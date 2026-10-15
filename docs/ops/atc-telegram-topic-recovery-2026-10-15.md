# ATC Telegram zaman dilimi konuları — 15 Ekim 2026

## Durum ve doğrulanmış bulgular

- 630 izleme hissesi, 18 özgün tarama koşulu korunuyor.
- Gün içi geçici günlük tarama: `CANLI / TEYİTSİZ` metin, görsel ve tam eşleşme CSV'si kodlandı; teyitsiz sonuçlar kesin tarama tablolarına yazılmıyor.
- Kesin zaman dilimi kartları: en çok 10 görsel sayfası + **tüm** eşleşmelerin CSV'si. Üretilen kartlar yalnızca gerçek `scan_evaluations` sonuçlarından geliyor.
- Daha önce ekran görüntüsünden tahmin edilen 60m=326, 240m=327, 1d=328, haftalık=329 **Bot API tarafından doğrulanmış değildir**. 328'e yapılan 15 Ekim gerçek canlı gönderim `400 Bad Request: message thread not found` verdi. Bu nedenle dört varsayılan eşleştirme koddan kaldırıldı.
- Bot'un `getUpdates` read-only tanılaması mevcut sohbet için yakın dönem topic update'i bulamadı; borsapp PostgreSQL'in başarıyla gönderilmiş eski mesajlarının kayıtlarında da zaman dilimi görsel topic'lerine ait kimlik çıkmadı.
- Başarısız 11 adet `ATC_1d_` dosyası, **yalnızca** reddedilen 328 konusu ve tam eşleşen hata için `available_at = infinity` kullanılarak otomatik yeniden denemeden çıkarıldı. Kayıtlar silinmedi; haber/diğer topic kayıtlarına dokunulmadı.
- Bu doğrulama tamamlanana kadar görsel yayın `--skip-if-unmapped` ile yanlış topic'e gitmeden atlanır. Yeni topic **oluşturulmaz** ve SCANS konusuna otomatik fallback **yapılmaz**.

## Konu kimliklerini kurtarma (kullanıcıdan istenecek)

Mevcut Telegram süpergrubunda 15, 30, 45, 60, 120, 240 dakika, Günlük, Haftalık başlıklarına girin. Her biri için yeni/son mesajın üzerinde **Mesaj bağlantısını kopyala** seçeneğini kullanarak bağlantıyı paylaşın. Eski ekran görüntülerinden message_thread_id tahmin etmeyin. Gerçek topic kimliği URL biçimine ve mümkünse o konu içinde bottan alınan `message_thread_id` alanına bakılarak doğrulanmalı. Bot tokeni veya kullanıcı oturum anahtarlarını paylaşmayın.

Doğrulanan sekiz değer daha sonra GitHub Actions repository variable `TELEGRAM_TIMEFRAME_TOPICS` içinde JSON eşlemesi olarak saklanabilir (ör. `{"15m":<id>,"30m":<id>,...}`; burada değerler **yer tutucudur**, gerçek ID değildir). Mevcut konu başlıkları dışında hiçbir yere görsel gönderilmemeli.

## Test ve tanılama

- `.github/workflows/atc-existing-topics-audit.yml`: doğrulanmış eşleştirmeler eksikse açık hata verir.
- `.github/workflows/atc-read-only-topic-discovery.yml`: yeni konu oluşturmadan son güncellemeleri okur; mesaj metinlerini / kullanıcı ID'lerini basmaz; offset ile update tüketmez.
- `.github/workflows/atc-telegram-visual-diagnostics.yml`: güvenli olarak yalnız ATC gönderim durumlarını ve hata örneklerini gösterir.
- `.github/workflows/atc-quarantine-rejected-topic.yml`: yalnız bilinen 328 hata kayıtlarına özgü kurtarma; yeniden çalıştırmak idempotenttir.
- `.github/workflows/atc-630-daily.yml`: günlük kesin tarama ve doğrulanmış topic için görsel denemesi; `scan-due` bazen `due=0` verebilir, bu gerçek yeni tarama yapıldığı anlamına gelmez.
- `.github/workflows/scheduled-scan.yml`: yalnız kapanmış mumun zaman dilimini çalıştırır; Telegram genel yayın kuyruğunu boşaltmaz.

**Not:** CI geçmesi Bot API teslimatı anlamına gelmez. Bir mesaj ancak `telegram_outbox.status = sent` ve Bot API `message_id` döndürdüğünde teslim edildi kabul edilir.
