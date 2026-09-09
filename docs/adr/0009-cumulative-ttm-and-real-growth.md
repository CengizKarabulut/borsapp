# ADR-0009: Kümülatif KAP akımları ve reel büyüme

Durum: Kabul edildi

## Bağlam

KAP ara dönem gelir ve nakit akış tabloları yılbaşından rapor tarihine kadar
kümülatif değerler taşır. Dört ardışık KAP sütununu toplamak aynı akımı birden
fazla kez sayar ve kârlılık, nakit üretimi ile değerleme çarpanlarını bozar.
Yfinance'ın çeyreklik tabloları ise ayrık dönemlerdir.

## Karar

- `borsapy:public_bist_statements` akım kalemleri için TTM; son YTD değerine
  önceki tam yıl eklenip önceki yılın aynı YTD değeri çıkarılarak hesaplanır.
- Referanslar liste sırasıyla değil tam takvim çeyreğiyle seçilir. Gerekli
  çeyreklerden biri yoksa sonuç `None/UNKNOWN` olur.
- Bilanço stok kalemleri TTM hesabına girmez.
- Yfinance ayrık çeyrekleri dört dönem toplamayı sürdürür.
- Önceki TTM karşılaştırması için borsapy sorguları 12 dönem ister.
- Reel büyüme, finansal akım döneminin bitiş ayına ait TCMB kaynaklı yıllık
  TÜFE ile Fisher ilişkisi kullanılarak hesaplanır. TÜFE alınamazsa nominal
  değer korunur ve reel yorum `UNKNOWN` olur; rapor üretimi başarısız olmaz.
- Sağlayıcı serbest metni yalnız yeterli Türkçe dil kanıtı varsa rapora girer.
  KAP'tan gelen Türkçe şirket unvanı, ASCII'ye indirgenmiş sağlayıcı unvanına
  tercih edilir.
- Finansal snapshot, saklanmış tarama/haber snapshot'ı ve TÜFE
  değeri/dönemi/kaynağı rapor kimliğine girer.

## Sonuçlar

Bu karar raporun finansal metriklerini değiştirdiği için paket sürümü
`0.1.1`, rapor şablonu `equity-research-tr-2.2.0` olarak artırılmıştır.
Eski ve yeni raporlar aynı artifact kimliğini paylaşmaz.
