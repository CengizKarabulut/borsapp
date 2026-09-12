# İşlem paneli

Tarama eşleşmeleri artık görsel panel ve tüm satırları içeren PDF ile sunulur. Önizleme alfabetik ilk 10 senaryodur; puan/başarı sıralaması değildir. PDF bütün senaryoları sayfalar. Kapsam, hesaplanamayan ve eksik veriler gizlenmez.

Ortak model `structural-atr-v1`: yalnız RAW ve tamamlanmış en az 15 mum. Wilder ATR14 ilk 14 gerçek aralık ortalamasıyla başlar. Long stop son 7 mumun en düşük fiyatının 0.2 ATR altı, short stop en yüksek fiyatın 0.2 ATR üstüdür. Risk en az 0.75 ATR olur. Yapısal stop riski küçültmek için içeri çekilmez. 3 ATR üzeri risk geniş stop olarak işaretlenir. TP1/2/3 riskin 1/2/3 katıdır. Negatif fiyat, sıfır oynaklık, düzeltilmiş fiyat bazı veya yetersiz veri için seviyeler üretilmez.

Giriş, sinyal mumunun kapanış referansıdır; gerçekleşmiş emir veya sonraki açılış fiyatı değildir. Yönsüz/karma bulgular iki koşullu senaryo üretir. Aşağı yönlü senaryo işlem yapılabilirliğini veya açığa satış iznini varsaymaz. Maliyetler hariçtir; modelin zaman dilimi/strateji bazında performansı henüz doğrulanmamıştır. Eski repodaki performans iddiaları bu modele taşınmamıştır. Kayıtlı `trade_plan` korunur; eksik olanlara ortak model eklenir.

Plan snapshot kimliği, kaynak, fiyat bazı, mum zamanı ve model sürümünü taşır. Eski eşleşmelerin görseli aynı snapshot kaynak/revizyon aralığındaki kayıtlı mumlardan hesaplanır; ileri tarihli veri kullanılmaz. Durum kayıtlarının eski sürümünde yön saklanmadığından bunlar koşullu olarak sunulur.

Fotoğraf ve PDF ortak outbox üzerinden kalıcı içerikle gönderilir. Yeniden başlatma aynı zaman dilimi/slot/medya kaydını yeniden kuyruğa eklemez.
