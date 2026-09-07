"""Projenin testleri.

Hepsi common.py icindeki saf fonksiyonlari dogrular: seri port, ekran veya
yonetici yetkisi gerekmez, suite bir saniyenin altinda calisir.

Calistirma:  pytest -v
"""

import statistics

import pytest

import common


# --------------------------------------------------------------------------- #
# Paket bicimi: encode / decode
# --------------------------------------------------------------------------- #
def test_encode_bir_satir_uretir():
    """Her ornek tam olarak bir satir olmali (satir sonu paket sinirini belirler)."""
    data = common.encode({"seq": 1, "cpu": 12.5})

    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1


def test_encode_bayt_dondurur():
    """Seri porta yalnizca bayt yazilabilir."""
    assert isinstance(common.encode({"cpu": 1.0}), bytes)


def test_decode_encode_isleminin_tersidir():
    """Kodlanip cozulen ornek aynen geri gelmeli."""
    sample = {"seq": 7, "ts": "2026-09-05T12:00:00.000", "cpu": 23.4,
              "mem": 48.0, "temp": 51.2, "temp_src": "lhm"}

    assert common.decode(common.encode(sample).strip()) == sample


@pytest.mark.parametrize("bozuk_satir", [
    b"",                       # bos satir
    b"{",                      # yarim JSON
    b"cpu=12.5",               # JSON degil
    b"[1, 2, 3]",              # JSON ama sozluk degil
    b'{"mem": 40.0}',          # zorunlu cpu alani yok
])
def test_decode_bozuk_satirda_none_dondurur(bozuk_satir):
    """Bozuk veri programi cokertmemeli, None donmeli."""
    assert common.decode(bozuk_satir) is None


# --------------------------------------------------------------------------- #
# Cerceveleme: split_lines
# --------------------------------------------------------------------------- #
def test_split_lines_tam_satiri_ayirir():
    lines, remainder = common.split_lines(b'{"cpu": 1}\n')

    assert lines == [b'{"cpu": 1}']
    assert remainder == b""


def test_split_lines_yarim_satiri_geride_birakir():
    """Yarim gelen paket bir sonraki okumayi beklemeli."""
    lines, remainder = common.split_lines(b'{"cpu": 1}\n{"cpu":')

    assert lines == [b'{"cpu": 1}']
    assert remainder == b'{"cpu":'


def test_split_lines_ayni_anda_gelen_iki_paketi_ayirir():
    lines, remainder = common.split_lines(b'{"a": 1}\n{"b": 2}\n')

    assert len(lines) == 2
    assert remainder == b""


# --------------------------------------------------------------------------- #
# Esik ustu istatistik
# --------------------------------------------------------------------------- #
def veri(cpu, mem=None, temp=None):
    """Test icin uc alanli veri sozlugu uretir."""
    return {
        "cpu": cpu,
        "mem": mem if mem is not None else [50.0] * len(cpu),
        "temp": temp if temp is not None else [45.0] * len(cpu),
    }


def test_sadece_esigi_asan_ornekler_secilir():
    sonuc = common.threshold_stats(veri([10.0, 30.0, 40.0, 5.0]), 20.0)

    assert sonuc["n"] == 2
    assert sonuc["total"] == 4


def test_esige_esit_deger_secilmez():
    """Karsilastirma > seklinde; sinir davranisini bu test sabitliyor."""
    sonuc = common.threshold_stats(veri([20.0, 20.0, 20.1]), 20.0)

    assert sonuc["n"] == 1


def test_ortalama_ve_standart_sapma_dogru_hesaplanir():
    degerler = [30.0, 40.0, 50.0, 60.0]

    ortalama, sapma, adet = common.threshold_stats(veri(degerler), 20.0)["cpu"]

    assert ortalama == pytest.approx(statistics.mean(degerler))
    assert sapma == pytest.approx(statistics.stdev(degerler))   # n-1 formulu
    assert adet == 4


def test_tek_ornekte_sapma_sifirdir():
    """statistics.stdev tek elemanla hata firlatir; kod bunu 0.0 yapiyor."""
    ortalama, sapma, adet = common.threshold_stats(veri([80.0]), 50.0)["cpu"]

    assert (ortalama, sapma, adet) == (80.0, 0.0, 1)


def test_esigi_asan_ornek_yoksa_bos_sonuc_doner():
    sonuc = common.threshold_stats(veri([10.0, 20.0]), 90.0)

    assert sonuc["n"] == 0
    assert sonuc["cpu"] == (None, None, 0)


def test_istatistik_tum_alanlar_icin_hesaplanir():
    """Secim olcutu CPU, ama hesap bellek ve sicaklik icin de yapilir."""
    data = veri(cpu=[10.0, 90.0, 95.0],
                mem=[40.0, 70.0, 80.0],
                temp=[45.0, 60.0, 70.0])

    sonuc = common.threshold_stats(data, 50.0)

    assert sonuc["cpu"][0] == pytest.approx(92.5)
    assert sonuc["mem"][0] == pytest.approx(75.0)     # dusuk CPU'lu ornek disarida
    assert sonuc["temp"][0] == pytest.approx(65.0)


def test_eksik_sicaklik_hesaba_katilmaz():
    """Sicaklik okunamadiysa None gelir ve ortalamayi bozmamali."""
    data = veri(cpu=[60.0, 70.0], temp=[50.0, None])

    sonuc = common.threshold_stats(data, 50.0)

    assert sonuc["temp"] == (50.0, 0.0, 1)
    assert sonuc["cpu"][2] == 2


# --------------------------------------------------------------------------- #
# Esik degeri dogrulama
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("metin, beklenen", [
    ("20", 20.0),          # tipik deger
    ("0", 0.0),            # alt sinir
    ("100", 100.0),        # ust sinir
    ("35.5", 35.5),        # ondalikli
    ("  42  ", 42.0),      # bastaki/sondaki bosluk temizlenir
])
def test_gecerli_esik_degerleri_kabul_edilir(metin, beklenen):
    assert common.parse_threshold(metin) == beklenen


@pytest.mark.parametrize("gecersiz", [
    "-1",        # negatif
    "-0.5",      # kucuk negatif
    "101",       # ust sinirin ustu
    "1000",      # cok buyuk
])
def test_aralik_disi_esik_reddedilir(gecersiz):
    """Esik yuzde degeri oldugu icin 0-100 disina cikamaz."""
    with pytest.raises(ValueError):
        common.parse_threshold(gecersiz)


@pytest.mark.parametrize("gecersiz", [
    "abc",       # harf
    "",          # bos
    "   ",       # sadece bosluk
    "12,5",      # virgullu yazim (Python nokta bekler)
    "20%",       # birim isareti
    None,        # hic deger yok
])
def test_sayi_olmayan_esik_reddedilir(gecersiz):
    """Sayiya cevrilemeyen giris sessizce 0 sayilmamali, hata vermeli."""
    with pytest.raises(ValueError):
        common.parse_threshold(gecersiz)


def test_hata_mesaji_kullaniciya_ne_yapacagini_soyler():
    """Mesaj sadece 'hata' dememeli, dogru bicimi ornekle gostermeli."""
    with pytest.raises(ValueError) as hata:
        common.parse_threshold("abc")

    assert "sayi" in str(hata.value).lower()

    with pytest.raises(ValueError) as hata:
        common.parse_threshold("-5")

    assert "0" in str(hata.value) and "100" in str(hata.value)


# --------------------------------------------------------------------------- #
# Yardimci fonksiyonlar
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("etiket, beklenen", [
    ("COM1  -  HHD Bridged Serial Port", "COM1"),
    ("COM3", "COM3"),
    ("", ""),
])
def test_port_adi_etiketten_ayiklanir(etiket, beklenen):
    assert common.port_from_label(etiket) == beklenen


def test_port_listesi_cift_dondurur():
    """Her giriste cihaz adi ve aciklama olmali."""
    for cihaz, aciklama in common.available_ports():
        assert isinstance(cihaz, str) and cihaz
        assert isinstance(aciklama, str)
