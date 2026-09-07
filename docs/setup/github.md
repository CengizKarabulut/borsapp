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
- `TELEGRAM_ALLOWED_USERS`
- sekiz adet `TELEGRAM_TOPIC_...` değeri

İlk shadow döneminde Telegram teslimatı kapalı tutulmalıdır. Canlı yayın için
ayrıca daha sonra eklenecek `DELIVERY_MODE=live` kapısı açılır; sadece secret
eklemek yayını başlatmamalıdır.

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

Son değişken eklenmezse veya `disabled` kalırsa haberler yalnız Neon'a yazılır.
5. PostgreSQL barındırma hedefi seçilmeden `DATABASE_URL` üretim secret'ı
   oluşturmayın.
