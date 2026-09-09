# Windows üzerinde sürekli yerel çalışma

Bu kurulum PostgreSQL, tarama motoru, Telegram listener/publisher, komut
worker'ı, haber akışı, BIST evren eşitlemesi, MA araştırması, outcome ölçümü ve
günlük yedeği aynı bilgisayarda çalıştırır. Neon çalışma zamanından çıkar.

## İlk kurulum

1. Docker Desktop'ı kurun ve ilk açılış sözleşmesini kabul edin.
2. PowerShell'i repo kökünde açın.
3. Aşağıdaki komutu çalıştırın:

       powershell -ExecutionPolicy Bypass -File scripts/windows/install-local.ps1

4. İstendiğinde bot tokenını ve Telegram grup kimliğini girin. Token ekranda
   görünmez ve yalnız Git tarafından dışlanan .env dosyasına yazılır.

Kurulum, güçlü bir yerel PostgreSQL parolası üretir, canlı servisleri başlatır
ve geçerli Windows kullanıcısı için Borsapp Local oturum-açma görevini kurar.
Docker motoru hazır olduğunda bütün servisler otomatik geri gelir.

## İşletim

- Durum ve son loglar: powershell -File scripts/windows/status-local.ps1
- Servisleri durdurma: powershell -File scripts/windows/stop-local.ps1
- Servisleri yeniden başlatma: powershell -File scripts/windows/start-local.ps1

PostgreSQL yalnız 127.0.0.1:5432 adresine açılır. Veriler Docker'ın
borsapp-postgres volume'unda kalır. Sıkıştırılmış günlük yedekler backups/
altında tutulur ve 14 günden eski yedekler otomatik silinir.

## Yerel görev aralıkları

- KAP ve genel haber: 10 dakika
- BIST Tüm evreni: 6 saat
- MA araştırması (4h ve 1d): 24 saat
- Outcome ölçümü: 24 saat
- PostgreSQL yedeği: 24 saat

GitHub Actions Telegram pulse, planlı tarama, haber ve araştırma işleri yerel
kurulum doğrulandıktan sonra kapatılmalıdır. Böylece iki listener aynı bot
update'ini almaya çalışmaz ve Neon'a yeni kayıt yazılmaz.
