# Migration çalışma alanı

Bu dizindeki üretilmiş raporlar karar değil keşif girdisidir.

- purity-audit.json: gizli I/O, saat, ortam, rastgelelik ve mutable state adayları
- indicator-map.json: indikatör tanımı ve kullanım adayları
- file-inventory.csv: kaynak dosya envanteri ve ilk işlem önerisi
- legacy-aliases.csv: çift yönlü ve elle doğrulanacak kimlik eşlemesi
- migration-map.csv: dosya/satır bazlı hedef kararları

İşlem sınıfları: TAŞI, BİRLEŞ, BÖL, SADELEŞTİR, GÖÇ, SİL, ARŞİV.
Ölü kod olduğu doğrulanmayan hiçbir dosya yalnız statik analiz sonucuyla silinmez.
