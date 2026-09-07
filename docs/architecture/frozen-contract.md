# Market Intelligence Suite — v4-final sözleşmesi

Bu belge mimari kararları dondurur. Bundan sonraki değişiklikler yeni bir tasarım
turu değil; ölçüm, ADR veya açık bir davranış değişikliği olarak ele alınır.

## Sınırlar

1. Scanner veri çekmez.
2. Scanner Telegram'a veya başka bir teslimat kanalına yazmaz.
3. Scanner gerçek sistem saatini ve ortam değişkenlerini doğrudan okumaz.
4. Scanner sıfır, bir veya birden fazla finding döndürebilir.
5. İndikatörler ortak feature katmanında hesaplanır.
6. Feature kimliği implementasyon, sürüm, parametre, warmup ve seed içerir.
7. Event ile state ayrı davranır ve ayrı saklanır.
8. MATCH, NO_MATCH ve UNKNOWN birbirinden ayrıdır.
9. State yalnız başarılı NO_MATCH gözlemiyle normal EXIT üretir.
10. Uzayan UNKNOWN terminal ABANDONED durumuna geçer.
11. UNKNOWN dönüşü RESUMED veya timing_uncertain EXIT_INFERRED üretir.
12. Sürüm/config değişimi SUPERSEDED + ADOPTED olarak modellenir ve bildirilmez.
13. İşlem durması instrument_halted olarak veri arızasından ayrılır.
14. Canonical kimlik ticker değil kalıcı instrument_id değeridir.
15. Sembol ve evren üyeliği valid_from/valid_to ile point-in-time saklanır.
16. Fiyat düzeltme politikası canonical seri kimliğinin parçasıdır.
17. Kapanmamış veya kabul edilmeyen kısmi mumda normal sinyal üretilmez.
18. Scheduler modulo değil watermark ile kaçan barları tamamlar.
19. Durum işleri birleştirilebilir; olay işleri kaybolmadan audit edilir.
20. İşleme kimliği data revision, scanner version ve ruleset hash içerir.
21. Bildirim kimliği deploy sürümünden bağımsız semantik olay kimliğidir.
22. Confluence puan veya tavsiye değil zaman pencereli kesişim bilgisidir.
23. UNKNOWN ve veri kapsamı confluence çıktısında görünürdür.
24. Sonuç/state değişimi ve outbox aynı operasyonel transaction içinde yazılır.
25. Telegram teslimatı at-least-once + semantik dedup olarak kabul edilir.
26. Tek Telegram update tüketicisi ve tek merkezi publisher bulunur.
27. Ağır GitHub Actions işleri doğrudan kullanıcı mesajı göndermez.
28. Legacy ve yeni motor aynı değişmez canonical snapshot üzerinde shadow çalışır.
29. Davranış değişikliği ADR ve engine-version artışı olmadan yapılamaz.
30. Scanner saflığı ve mimari bağımlılık sınırları CI ile denetlenir.

## Veri akışı

    Platform
      └─ Ingestion
           └─ Replay/Canonical Snapshot Store
                └─ Canonical Bars
                     └─ Features
                          └─ Scanning
                               ├─ Event Store
                               └─ State Store
                                    └─ Application Services
                                         └─ Transactional Outbox
                                              └─ Telegram Publisher

Platform; takvim, kimlik, yapılandırma, observability ve idempotency
sorumluluklarını yatay olarak sağlar.

## Confluence pencereleri

- strict: aynı timeframe ve aynı kapanmış bar
- recent_n: aynı timeframe içinde açıkça belirtilen son N bar
- cross_timeframe: her timeframe'in son doğrulanmış kapanmış barı

Sıralama önce aile kapsamı, yön tutarlılığı, veri tazeliği ve pencere
sıkılığıyla yapılır. Ham eşleşme sayısı yalnız açıklayıcıdır.

## Göç yöntemi

Strangler + shadow uygulanır. Eski sistem kullanıcı yayınına devam ederken yeni
motor aynı snapshot üzerinde sessizce hesaplanır. Farklar açıklanmadan kaynak
scanner kapatılmaz. Bilinçli davranış farkları ADR ile kaydedilir.

İlk dikey dilimler:

1. technical.volume_spike
2. signal.macd_positive_cross
3. ma.near_zone

MACD referans implementasyonu shadow sonucu görülmeden önce ADR ile seçilecektir.
