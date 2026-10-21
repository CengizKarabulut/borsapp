# GitHub canlı taraması için yerel tetikleme yedeği

GitHub `schedule` olayları bazen saatler sonra başlayabildiğinden, açık ve kullanıcı oturumu açık olan Windows bilgisayarından aynı mevcut workflow'a tetikleme göndermek mümkündür. Bu yöntem hesaplamayı Windows'a taşımaz; GitHub'daki işin başlaması, piyasa verisinin gelmesi ve 630 hissenin hesaplanması hâlâ zaman alır. Bildirimin kesin dakikada gelmesini garanti etmez.

`scripts/windows/dispatch-atc-snapshot-due.ps1`, açık `-Dispatch` olmadan yalnızca yerel kontrol yapar; GitHub'a bağlanmaz. Gerçek modda kurulu ve SHA256 ile doğrulanmış GitHub CLI'ın mevcut kullanıcı girişini kullanır. Token veya parola yazdırmaz, Telegram sırrı okumaz, E'deki geçmiş veriye veya emir kanalına dokunmaz.

Gönderilecek tek komutun sabit hedefi:

```text
gh workflow run atc-scheduled-snapshots.yml --repo CengizKarabulut/borsapp --ref main -f scope=due -f delivery=publish
```

Betik hafta içi Türkiye saatiyle 10:07–18:45 aralığı dışındaysa iş yapmaz. İşlem tatillerini ve hangi dönemin gerçekten taranacağını GitHub'daki mevcut BIST planlayıcısı belirler. Yerel görev 10:07–17:52 arasında her 15 dakikada bir ve 18:30'da tetiklenmek üzere hazırlanır. Geciken tetikleme en son vadesi gelen dönemi ister; eski açık mumları geriye dönük üretmez.

Görev için mevcut kullanıcı, `InteractiveToken` / `LeastPrivilege`, `IgnoreNew`, `StartWhenAvailable=true`, `WakeToRun=false` kullanılır. Yönetici yetkisi veya kaydedilmiş parola gerekmez. Betik ayrıca aynı anda iki çağrıyı önleyen C üzerinde bir dosya kilidi kullanır. C'deki küçük durum kaydı `dispatch_accepted_delivery_not_yet_verified` diyebilir; bu, Telegram'a teslim kanıtı değildir. Asıl teslim ve dönem tekrar kontrolü GitHub workflow'unun gerçek Telegram makbuzlarıyla yapılır.

Bilgisayar kapalı veya kullanıcı oturumu kapalıysa bu yedek çalışamaz; GitHub'ın mevcut cron'u korunur. Destek/direnç raporu için ikinci bir yerel çağrı eklenmez: 08:35 GitHub yayınının henüz ayrı dönem teslim defteri olmadığından aynı günlük raporu iki kez göndermemeliyiz.

Salt okunur sınama örneği:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "TAM_REPO_YOLU\scripts\windows\dispatch-atc-snapshot-due.ps1" -Now '2026-10-21T10:07:00+03:00'
```

Saat örneği `-Now`, yalnızca bu kuru kontrol için kabul edilir; `-Dispatch` ile birlikte kullanılamaz. Betik görev kurmaz. Hazırlanmış görev XML'i ve açık kurulum/geri alma adımları ayrı gözden geçirilir.
