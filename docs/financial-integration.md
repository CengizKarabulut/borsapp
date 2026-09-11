# KAP finansalları, rapor ve birleşim doğrulaması

Doğrulanmış uygulama sürümü 2026-09-11 tarihinde mevcut laptop Docker kurulumuna alınmıştır. Tüm uygulama servisleri `borsapp:news-review` ile aynı imaj kimliğini kullanır; finansal arşivleme servisi etkindir. Kullanıcı onayıyla mevcut canlı PostgreSQL başlatıldı, yeniden başlatma politikası konteynerde ve canlı Compose dosyasında `unless-stopped` olarak düzeltildi.

## Veri akışı

KAP finansal bildirimleri resmi uç noktadan alınır. Ham yanıt ve PDF ekleri SHA-256 ile arşivlenir; aynı bildirimin sonraki sürümleri eski gözlemleri silmez. Bilanço, gelir tablosu ve nakit akışındaki kesin taksonomi alanları para birimi, ölçek, dönem ve konsolidasyon bilgileriyle eşleştirilir. Eksik borç, nakit veya yatırım harcaması sıfır varsayılmaz.

Güncel fiyat önce borsapy, sonra yfinance üzerinden denenir. borsapy finansal tablo yedeği İş Yatırım kaynaklıdır; bu veriler resmi KAP diye etiketlenmez. Fiyatın kaynak ve erişim zamanı saklanır. Sağlayıcı işlem zamanını doğrulamıyorsa kesin 15 dakika gecikme iddiası üretilmez.

TMS-29 karşılaştırmaları ikinci kez enflasyondan arındırılmaz. Farklı satın alma gücü tarihli geçmiş resmi tablolar, uygun baz doğrulandığında aylık TÜFE oranlarıyla yaklaşık olarak ortak baza getirilir. Bu işlem şirketin kesin düzeltme katsayısı olarak sunulmaz. Doğrulanamayan tarih/baz için reel büyüme yorumu verilmez. Arşiv erişim zamanı, geçmişte yayımlanmış olma bilgisiyle aynı kabul edilmez.

## Yerel komutlar

Önce editable kurulum yapın: `python -m pip install -e ".[runtime]"`.

```powershell
# İlk yükleme: yaklaşık altı yıl. KAP erişim kapsamı ve sağlayıcı hataları sonuçta bildirilir.
borsapp financial-sync --symbols MEPET,ASELS --lookback-days 2190
# Sonraki çalışmalarda yeni bildirim ve düzeltmeleri ekle.
borsapp financial-sync --symbols MEPET,ASELS --lookback-days 7
# Hesaplama ve kaynak dökümü; Telegram göndermez.
borsapp financial-report MEPET --output output/MEPET.json
# Yeni ve boş hedef dizine tutarlı SQLite + referans verilen KAP belgeleri.
borsapp financial-backup --destination backups/financials-20260910
# Üretim PDF renderer'ı ile gerçek veri önizlemesi; DB veya Telegram gerekmez.
python scripts/preview_equity_report.py MEPET --output output/MEPET.pdf
```

Varsayılan arşiv `data/financial_archive`; `--archive-root` veya `BORSAPP_FINANCIAL_ARCHIVE` ile değişir. `--universe BIST_ALL` seçimi PostgreSQL enstrüman kataloğunu kullanır. Bootstrap tamamlanma işareti yalnızca hatasız indirme sonrasında kaydedilir; eklenen semboller yeniden bootstrap başlatabilir.

## Kalıcı Docker verisi

`borsapp-financials` volume'u command-worker ve financial-worker tarafından paylaşılır. İmaj yeniden oluşturulduğunda finansallar kaybolmaz. PostgreSQL yedeği bu volume'u kapsamaz; ayrıca finansal yedek alınmalıdır.

`runtime` ve `financials` profilleri birlikte kullanılır. Financial-worker ilk başarılı çalışmada 2190 günlük geçmişi, ardından her gün son 7 günü kontrol eder. Yeni profili etkinleştirme canlı kurulum adımıdır; önce imaj ve izole uçtan uca test yapılmalıdır.

```sh
docker compose --profile runtime --profile financials config --no-env-resolution --quiet
# Çalışan command-worker içinde, geçici alana doğrulanmış yedek:
docker compose exec command-worker borsapp financial-backup --destination /tmp/financials-backup-20260910
docker compose cp command-worker:/tmp/financials-backup-20260910 ./backups/financials-backup-20260910
```

Yedekleme canlı SQLite dosyasını doğrudan kopyalamaz; SQLite backup API ile tutarlı anlık görüntü alır ve bu görüntünün referans verdiği belgeleri hash kontrolüyle kopyalar. `backup-manifest.json` yalnızca tüm adımlar başarıyla tamamlandığında yazılır. Var olan hedefin üzerine yazılmaz. Geri yükleme, finansal yazıcılar durdurulduktan sonra yedekteki veritabanı ve `kap/` dizininin boş arşiv dizinine kopyalanmasıyla yapılır. Varsayım dosyaları ve bootstrap işaretleri bu veri yedeğine dahil değildir; varsayımlar ayrıca sürümlenmelidir. Yeniden bootstrap güvenlidir; geçmiş kayıtlar silinmez.

## Hesaplamalar ve sınırlar

Veri yeterliyse TTM gelir/kâr/nakit akışı, CFO eksi yatırım harcaması, bilanço oranları, güncel fiyatla piyasa değeri ve çarpanlar hesaplanır. Standart FAVÖK için veri yoksa faaliyet kârı + amortisman yalnızca açıkça etiketlenmiş bir yaklaşım olarak sunulur.

CAPM, WACC, FCFF, DCF ve duyarlılık aritmetiği uygulanmıştır. Ancak gelecekteki satış, marj, yatırım, işletme sermayesi, vergi, iskonto oranı ve terminal büyüme yalnızca tarihsel KAP ve fiyat verilerinden kesin biçimde çıkarılamaz. Kullanıcı varsayımları olmadan hedef fiyat üretilmez. `financial-report --assumptions DOSYA.json` veya rapor servisinde `<archive>/assumptions/<SEMBOL>.json` kullanılır. Şema örneği `config/valuation-assumptions.example.json` dosyasındadır. `example_only: true` işaretli dosya gerçek şirketi değerlemek için reddedilir; sayılar şirket verisi veya tavsiye değildir. Girdiler `research/valuation.py` sözleşmesine uymalı; tüm tutarlar tam para birimi, oranlar kesir, pay sayısı toplam seyreltilmiş pay sayısı olmalıdır. Nakit akışı ve iskonto oranı aynı para birimi ve nominal/reel bazda olmalıdır. WACC terminal büyümeden büyük olmalıdır.

Banka, sigorta, GYO ve holding gibi şirketlerde genel FCFF yerine sektöre özgü modeller gerekir. Bu çalışma tüm sektörlerin taksonomisini ve bütün dipnot kalemlerini kapsadığını iddia etmez. Eksik veri açıkça raporlanır. İş Yatırım/yfinance yedeklerinde ortak satın alma gücü bazı doğrulanmadığında farklı dönemlerden TTM toplamı oluşturulmaz. Yıllık kümülatif tek rapor tutarı ve bilanço kalemleri kullanılabilir. Bu yüzden bazı oranlar resmi KAP verisi bulunana kadar boş kalabilir.

## Onaylanmış düzeltmeler

- Farklı dönem/para birimi/bazdaki finansal verilerin gelişigüzel birleştirilmesi engellendi.
- Finansal yayımlanma ve erişim zamanı ayrıldı; TMS-29 baz kontrolleri eklendi.
- NEWS hisse adayları doğrulanmış enstrüman kodlarıyla sınırlandı; boş TradingView içeriği yeniden zenginleştiriliyor.
- Haber metnindeki HTML artıkları temizleniyor; paragraf sınırları ve başlık/gövde ayrımı korunuyor.
- Grafik üretimi korunarak dosya teslimi ortak outbox'a taşındı. Kuyruk kaydı, gönderilmiş teslimat olarak sunulmuyor.
- Docker imajına dört legacy kaynak ağacı dahil edildi.

## NEWS sürüm tutarlılığı

Kullanıcı onayıyla başlık ve gövde aynı gelen haber kaydından birlikte güncellenir. Yeni, daha kısa bir tam içerik de eski uzun açıklamanın yerini alır. Başlık, yayın tarihi veya URL değiştiğinde ayrıntılar yeniden istenir. Kimliği değişmemiş tam bir habere gelen sıradan liste özeti mevcut tam kaydı düşürmez; bu durumda eski kayıt bütünüyle korunur. Yeni başlık henüz ayrıntısız geldiyse eski gövdeyle karıştırılmaz ve sonraki taramada zenginleştirme yeniden denenir.

## Doğrulama durumu — 2026-09-11

- Windows/Python 3.13: gerçek, izole PostgreSQL bağlantısıyla 279 test geçti; hata ve atlama yok. Ruff ve Compose yapılandırma kontrolü başarılı.
- Önceki Linux/Python 3.12 doğrulaması: 278 test çalıştı; 277 geçti, örnek `.env.example` dosyasını okuyan test dosya imajda olmadığı için hata verdi. Yalnızca bu örnek dosya salt okunur bağlandıktan sonra ilgili test de geçti. Uygulama kodunda test için değişiklik yapılmadı.
- Güncel imaj: `borsapp:news-review`; doğrulanan kimlik `sha256:3a9d6d5b5eaa90193cd21606f2225a8aae1ef278976f8bd33049af91d544d820`. NEWS düzeltmesinden sonra bu imajda 17 haber/gerçek PostgreSQL testi geçti. Ana Dockerfile ile oluşturulan imaja son kaynak düzeltmeleri ek bir build katmanıyla kuruldu; tüm bağımlılıklar ilk imajdan kullanıldı.
- Gerçek ASELS günlük grafiği Linux imajında üretildi: 685961 bayt PNG. Telegram gönderimi çağrılmadı.
- MEPET: 400 günlük resmi KAP taramasında 16 bildirim (5 finansal tablo, 11 ek belge), indirme hatası yok.
- ASELS ve THYAO: toplam 24 bildirim (8 finansal tablo, 16 ek belge), indirme hatası yok. Bin TL ve 1.000.000 TL sunum biçimleri test edildi. Üç şirket için 2026-06-30 dönemli temel hesaplamalar hatasız çıkarıldı.
- Gerçek verili MEPET PDF’si 13 sayfa; tüm sayfalar görsel olarak incelendi. Bu önizleme bir yatırım tavsiyesi veya doğrulanmış kurumsal hedef fiyat değildir.
- Üç şirketi içeren finansal yedek 52 dosyadan oluşuyor; SQLite ve SHA-256 kontrolleri başarılı. Aynı Windows arşivi Linux imajına salt okunur bağlanarak yeniden yedeklendi; 52 dosya kontrolü orada da geçti.
- Canlı PostgreSQL, listener, command-worker, publisher ve scanner son kontrolde healthy. Veritabanı `unless-stopped` politikasına geçirildi. Bu operasyon yeni uygulama imajının canlıya dağıtıldığı anlamına gelmez.

## Kalan işler

NEWS başlık/özet düzeltmesi kullanıcı onayıyla uygulanmıştır. BIST_ALL için ilk kapsamlı finansal bootstrap çalışmaktadır; tamamlanma işareti yalnızca hatasız bitişte yazılır. Mevcut arşiv bu sırada kullanılabilir. GitHub sürümü entegrasyon dalı ve CI üzerinden yayımlanır. Sektöre özel değerleme modelleri ve şirket bazlı geleceğe dönük varsayımlar bu sürümün otomatik kapsadığı alanlar değildir.

## Canlı geçiş kontrolü

2026-09-11: PostgreSQL yedeği (154841786 bayt) alınıp pg_restore katalog kontrolünden geçirildi. Önceki kaynak dosyaları ve imajlar geri dönüş için korundu. Mevcut `.env`, Telegram hedefleri ve PostgreSQL volume'u korundu. Windows açılış betikleri `financials` profilini de başlatacak şekilde güncellendi; kayıtlı `Borsapp Local` görevinin doğru dizine bağlı olduğu doğrulandı.

Canlı doctor sonucu: veritabanı ve migration'lar hazır; BIST_ALL 583 aktif üye; bekleyen/hatalı outbox 0/0. Scanner, listener, publisher ve command-worker healthy; tüm uygulama servisleri doğrulanan imajı kullanıyor. Finansal arşivde ilk canlı kontrolde 73 KAP gözlemi ve 5 şirket görüldü; başlangıç yedeği 3 şirket içerdiği için yeni veri yazıldığı doğrulandı. Bu sayılar anlık kontroldür, arşiv yükleme sırasında büyür.
