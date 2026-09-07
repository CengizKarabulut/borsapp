"""BIST sembol listesi.

Neden gerekli: "AAPL" ile "THYAO" bicimsel olarak ayirt edilemez, ikisi de
buyuk harfli dort-bes karakterdir. Sembolu dogru saglayiciya yollamak icin
elimizde bir BIST kod listesi olmasi gerekiyor.

Liste eskirse (yeni halka arzlar, kod degisiklikleri) su komutla tazeleyin:

    python -m src.bist_symbols --refresh

Bu komut borsapy'nin sirket listesini cekip bu dosyayi yeniden yazar.
Listede olmayan bir BIST kodunu tek seferlik zorlamak icin "bist:" oneki
kullanilabilir: ``--symbol bist:YENIK``.
"""

from __future__ import annotations

from pathlib import Path

BIST_SYMBOLS: frozenset[str] = frozenset(
    """
ACSEL ADEL ADESE ADGYO AEFES AFYON AGESA AGHOL AGROT AGYO AHGAZ AKBNK AKCNS AKENR
AKFGY AKFYE AKGRT AKMGY AKSA AKSEN AKSGY AKSUE AKYHO ALARK ALBRK ALCAR ALCTL ALFAS
ALGYO ALKA ALKIM ALMAD ALTINS1 ANELE ANGEN ANHYT ANSGR ARASE ARCLK ARDYZ ARENA ARSAN
ARTMS ARZUM ASELS ASGYO ASTOR ASUZU ATAGY ATAKP ATATP ATEKS ATLAS ATSYH AVGYO AVHOL
AVOD AVPGY AVTUR AYCES AYDEM AYEN AYES AYGAZ AZTEK BAGFS BAKAB BALAT BANVT BARMA
BASCM BASGZ BAYRK BERA BEYAZ BFREN BIENY BIGCH BIMAS BINHO BIOEN BIZIM BJKAS BLCYT
BMSCH BMSTL BNTAS BOBET BORLS BORSK BOSSA BRISA BRKSN BRKVY BRLSM BRMEN BRSAN BRYAT
BSOKE BTCIM BUCIM BURCE BURVA BVSAN BYDNR CANTE CASA CATES CCOLA CELHA CEMAS CEMTS
CEOEM CIMSA CLEBI CMBTN CMENT CONSE COSMO CRDFA CRFSA CUSAN CVKMD CWENE DAGHL DAGI
DAPGM DARDL DENGE DERHL DERIM DESA DESPC DEVA DGATE DGGYO DGNMO DIRIT DITAS DMSAS
DNISI DOAS DOBUR DOCO DOFER DOGUB DOHOL DOKTA DURDO DYOBY DZGYO ECILC ECZYT EDATA
EDIP EGEEN EGEPO EGGUB EGPRO EGSER EKGYO EKIZ EKOS EKSUN ELITE EMKEL EMNIS ENERY
ENJSA ENKAI ENSRI EPLAS ERBOS ERCB EREGL ERSU ESCAR ESCOM ESEN ETILR ETYAT EUHOL
EUKYO EUPWR EUREN EUYO EYGYO FADE FENER FLAP FMIZP FONET FORMT FORTE FRIGO FROTO
FZLGY GARAN GEDIK GEDZA GENIL GENTS GEREL GESAN GIPTA GLBMD GLCVY GLRYH GLYHO GMTAS
GOKNR GOLTS GOODY GOZDE GRNYO GRSEL GSDDE GSDHO GSRAY GUBRF GWIND GZNMI HALKB HATEK
HATSN HDFGS HEDEF HEKTS HKTM HLGYO HRKET HTTBT HUBVC HUNER HURGZ ICBCT ICUGS IDGYO
IEYHO IHAAS IHEVA IHGZT IHLAS IHLGM IHYAY IMASM INDES INFO INGRM INTEM INVEO INVES
IPEKE ISATR ISBIR ISBTR ISCTR ISDMR ISFIN ISGSY ISGYO ISKPL ISMEN ISSEN ISYAT IZENR
IZFAS IZINV IZMDC JANTS KAPLM KAREL KARSN KARTN KATMR KAYSE KBORU KCAER KCHOL KENT
KERVT KFEIN KGYO KIMMR KLGYO KLKIM KLMSN KLRHO KLSER KLSYN KMPUR KNFRT KOCMT KONKA
KONTR KONYA KOPOL KORDS KOTON KOZAA KOZAL KRDMA KRDMB KRDMD KRGYO KRONT KRPLS KRSTL
KRTEK KRVGD KSTUR KTLEV KTSKR KUTPO KUYAS KZBGY KZGYO LIDER LIDFA LILAK LINK LKMNH
LMKDC LOGO LRSHO LUKSK MAALT MACKO MAGEN MAKIM MAKTK MANAS MARBL MARKA MARTI MAVI
MEDTR MEGAP MEGMT MEKAG MEPET MERCN MERIT MERKO METRO METUR MGROS MHRGY MIATK MIPAZ
MMCAS MNDRS MNDTR MOBTL MPARK MRGYO MRSHL MSGYO MTRKS MTRYO MZHLD NATEN NETAS NIBAS
NTGAZ NTHOL NUGYO NUHCM OBAMS OBASE ODAS ODINE OFSYM ONCSM ONRYT ORCAY ORGE ORMA
OSMEN OSTIM OTKAR OTTO OYAKC OYAYO OYLUM OYYAT OZGYO OZKGY OZRDN OZSUB OZYSR PAGYO
PAMEL PAPIL PARSN PASEU PATEK PCILT PEHOL PEKGY PENGD PENTA PETKM PETUN PGSUS PINSU
PKART PKENT PLTUR PNLSN PNSUT POLHO POLTK PRDGS PRKAB PRKME PRZMA PSDTC PSGYO QUAGR
RALYH RAYSG REEDR RGYAS RNPOL RODRG ROYAL RTALB RUBNS RYGYO RYSAS SAFKR SAHOL SAMAT
SANEL SANFM SANKO SARKY SASA SAYAS SDTTR SEGMN SEGYO SEKFK SEKUR SELEC SELGD SELVA
SEYKM SILVR SISE SKBNK SKTAS SKYLP SMART SMRTG SNGYO SNICA SNKRN SODSN SOKE SOKM
SONME SRVGY SUMAS SUNTK SURGY SUWEN TABGD TARKM TATEN TATGD TAVHL TBORG TCELL TDGYO
TEKTU TERA TEZOL TGSAS THYAO TKFEN TKNSA TLMAN TMPOL TMSN TNZTP TOASO TRCAS TRGYO
TRILC TSGYO TSKB TSPOR TTKOM TTRAK TUCLK TUKAS TUPRS TUREX TURGG TURSG UFUK ULAS
ULKER ULUFA ULUSE ULUUN UNLU USAK UZERB VAKBN VAKFN VAKKO VANGD VBTYZ VERTU VERUS
VESBE VESTL VKFYO VKGYO VKING VRGYO YAPRK YATAS YAYLA YBTAS YEOTK YESIL YGGYO YGYO
YKBNK YKSLN YONGA YUNSA YYAPI YYLGD ZEDUR ZOREN ZRGYO
""".split()
)

_HEADER_END = "BIST_SYMBOLS: frozenset[str] = frozenset(\n    \"\"\"\n"


def is_bist(code: str) -> bool:
    return code.upper() in BIST_SYMBOLS


def refresh(path: str | Path | None = None) -> int:
    """borsapy'den guncel sirket listesini cekip bu dosyayi yeniden yazar."""
    import borsapy as bp

    companies = bp.companies()
    if hasattr(companies, "columns"):  # DataFrame
        column = next(
            (c for c in companies.columns if str(c).lower() in {"code", "symbol", "kod", "ticker"}),
            companies.columns[0],
        )
        codes = sorted({str(v).strip().upper() for v in companies[column] if str(v).strip()})
    else:
        codes = sorted({str(v).strip().upper() for v in companies})

    if len(codes) < 100:
        raise RuntimeError(f"Beklenenden az sembol dondu ({len(codes)}), dosya guncellenmedi")

    target = Path(path) if path else Path(__file__)
    text = target.read_text(encoding="utf-8")
    start = text.index(_HEADER_END) + len(_HEADER_END)
    end = text.index('"""\n)', start)

    lines, current = [], ""
    for code in codes:
        if len(current) + len(code) + 1 > 92:
            lines.append(current.rstrip())
            current = ""
        current += code + " "
    if current.strip():
        lines.append(current.rstrip())

    target.write_text(text[:start] + "\n".join(lines) + "\n" + text[end:], encoding="utf-8")
    return len(codes)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BIST sembol listesini tazele")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.refresh:
        print(f"{refresh()} sembol yazildi")
    else:
        print(f"{len(BIST_SYMBOLS)} sembol kayitli")
