# Düzeltilmiş geçmiş testinin Windows açılışında devamı

`scripts/windows/ensure-corrected-replay.ps1`, mevcut doğrulanmış Stop/TP araştırmasını gözetmek için hazırlanmış bir Windows PowerShell 5.1 betiğidir. Tek başına zamanlanmış görev kurmaz. `-Resume` verilmeden yalnızca durum okur; araştırma veya başka işlem başlatmaz.

Betik, işlem numarasına güvenmek yerine tam araştırma betiği yolunu, `--root` parametresini, Windows kullanıcısını ve gerektiğinde işlemin oluşturulma zamanını kontrol eder. Python ortam başlatıcısı ile onun altındaki gerçek Python işlemi tek çalışma olarak sayılır. Çalışma varsa büyük özet dosyası veya geçmiş manifesti yeniden okunmaz.

E diski bağlı değilse bekler. `results/exit-research-adjusted-v2/replay-v4/stop.request` varsa yeniden başlatmaz. Araştırma bitmişse yeniden başlatmaz. Yeniden başlatma gerektiğinde yalnızca SHA256 değerleri sabitlenmiş mevcut `Resume-CorrectedReplay.ps1` ve onun salt okunur ön kontrolü üzerinden ilerler. Değişmez araştırma kodu, geçmiş mumlar, iki işçi sınırı, komisyon veya Stop/TP araştırma koşulları değiştirilmez. Yeni başlangıç ancak yeni yardımcı süreç kaydı ve gerçekten açık, aynı kullanıcıya ait Python işlemi doğrulandığında başarılı sayılır.

## Salt okunur kontrol

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "TAM_REPO_YOLU\scripts\windows\ensure-corrected-replay.ps1"
```

Çalışan araştırmada `observed_existing_same_user_replay`, `summary_read:false` ve `resume_helper_invoked:false` beklenir. Bu kontrol C veya E üzerinde durum dosyası yazmaz.

## İsteğe bağlı proje görevinin kurulma planı

Kurulum ayrı olarak gözden geçirilmelidir. Hazırlanan betik henüz görev kurmuş değildir.

Windows Görev Zamanlayıcı için önerilen yapılandırma:

- Mevcut Windows kullanıcısı; `InteractiveToken`, `Limited`; yönetici yetkisi veya kaydedilmiş parola kullanılmaz.
- Kullanıcı oturum açtığında başlatma ve her beş dakikada bir kontrol.
- Aynı görev zaten çalışıyorsa yeni örnek başlatmama: `IgnoreNew`.
- Eylem: gizli Windows PowerShell, `-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "TAM_BETIK_YOLU" -Resume`.
- Gerekirse açık `-ResumeHelperPath "DOGRULANMIS_YARDIMCI_YOLU"` ve `-CStatePath "C_UZERINDE_DURUM_YOLU"` parametreleri.
- Görev için üç dakikalık üst süre; çalışma devamı ayrı doğrulanmış yardımcı süreç üzerinden yürür.

Görev mevcut kullanıcı Windows'a oturum açınca çalışabilir. Bilgisayar kapalıyken veya kullanıcı oturumu kapalıyken hesaplama yapmaz. Global güç ayarını değiştirmez. Görevin adı ve kaydedilmiş eylemi kurulum kaydında saklanmalı; kullanıcı Görev Zamanlayıcı'dan bu görevi devre dışı bırakabilmeli veya silebilmelidir.

`-Resume` kullanıldığında C üzerinde küçük, dönen `supervisor.log`, son gözlem dosyası ve tek örnek kilidi oluşur. Bu kilit, aynı anda elle başlatılan kontrol ile zamanlanmış kontrolün de üst üste başlamasını engeller. Bir kayıtta `observed_existing...` yazması o işlemin gelecekte hâlâ açık olduğunu kanıtlamaz; kayıt gözlem zamanını taşır ve her kontrolde gerçek süreç yeniden sorgulanır.

Beklenmeyen kod değişikliği, farklı kullanıcı, birden çok çalışma ağacı veya doğrulanamayan yeni başlangıçta betik durur; ikinci bir yoldan başlatmayı denemez. Bu gözetici alarm, Telegram mesajı, yeni veri indirmesi, profil etkinleştirmesi veya emir gönderimi yapmaz.
