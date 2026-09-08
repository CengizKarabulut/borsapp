# GitHub kullanıcı kurulum kontrol listesi

## Actions secrets

Repository > Settings > Secrets and variables > Actions > **Secrets**:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `DATABASE_URL` — üretim PostgreSQL adresi hazır olduğunda

Token ve parola yalnız secret olarak tutulur. Topic ID değerleri gizli değildir,
ancak ortamlar arasında değiştiğinden Actions **Variables** altında tutulur.

## Actions variables

- `APP_TIMEZONE=Europe/Istanbul`
- `TELEGRAM_ALLOWED_USERS`: Telegram'da kendi botunuza `/kimlik` göndererek
  aldığınız gerçek kullanıcı ID'si; bot ID'si değildir
- `TELEGRAM_ALLOW_CHAT_ADMINS=true`: Komut Merkezi'nde grup yöneticilerini
  dinamik olarak yetkilendirir; yanlış statik kullanıcı ID'sinin botu kilitlemesini önler
- `TELEGRAM_ALLOW_CHAT_MEMBERS=true`: yalnız yapılandırılmış özel gruptaki tüm
  üyelerin komut vermesine izin verir; başka gruplar kabul edilmez
- sekiz adet `TELEGRAM_TOPIC_...` değeri

İlk kurulum tamamlanınca `/kimlik` yanıtındaki kullanıcı ID'sini kaydedin ve
dar yetkilendirme için `TELEGRAM_ALLOW_CHAT_MEMBERS=false` ile
`TELEGRAM_ALLOW_CHAT_ADMINS=false` yapın. `true` değerleri yalnız ilk kimlik
tespiti veya bilinçli grup-geneli kullanım içindir.

Canlı zamanlanmış tarama yalnız `1h`, `4h` ve `1d` sonuçlarını Taramalar
konusuna yollar. `15m`, `30m`, `45m` ve `2h` hesaplanır ve saklanır fakat
Telegram'a yayınlanmaz.

## Repo ayarları

1. Settings > Branches altında `main` için branch protection açın.
2. Merge öncesi **CI** kontrolünü zorunlu yapın.
3. Actions izinlerini başlangıçta **Read repository contents** düzeyinde tutun.
4. Legacy workflow dosyaları `_legacy` altında olduğundan otomatik çalışmaz;
   eski dört repodaki workflow'ları şimdilik kapatmayın.

Zamanlanmış yeni akışlar ayrı repo değişkenleriyle açılır:

- `ENABLE_SCHEDULED_SCANS=true`: kapanmış mum taramaları
- `ENABLE_SCHEDULED_RESEARCH=true`: MA Research yenilemesi
- `ENABLE_SCHEDULED_NEWS=true`: KAP haber eşitlemesi
- `NEWS_DELIVERY_MODE=live`: yeni KAP kayıtlarını Haberler & KAP konusuna yayınlar
- `ENABLE_TELEGRAM_PULSE=true`: kalıcı host kurulana kadar gecikmeli canlı komut botu

Son değişken eklenmezse veya `disabled` kalırsa haberler yalnız Neon'a yazılır.
5. PostgreSQL barındırma hedefi seçilmeden `DATABASE_URL` üretim secret'ı
   oluşturmayın.
