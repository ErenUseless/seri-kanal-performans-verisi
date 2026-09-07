"""Iki arayuzun paylastigi ortak katman.

Icerik: seri port listesi, sistem olcumleri, sicaklik okuma, paket bicimi
(kodlama / cozme / satirlara ayirma) ve esik ustu istatistik.

Paket bicimi: her ornek tek satirlik JSON, '\n' ile biter.
{"seq": 1, "ts": "2026-09-05T12:00:00.123", "cpu": 12.3, "mem": 55.1,
 "temp": 45.0, "temp_src": "lhm"}
"""

import json
import os
import statistics
import sys
from datetime import datetime

import psutil
from serial.tools import list_ports

# Olculen uc alan ve grafikte kullanilan etiketleri
FIELDS = ("cpu", "mem", "temp")
FIELD_LABELS = {
    "cpu": "CPU Kullanimi (%)",
    "mem": "Bellek Kullanimi (%)",
    "temp": "Sicaklik (C)",
}


# --------------------------------------------------------------------------- #
# Seri portlar
# --------------------------------------------------------------------------- #
def available_ports():
    """Sistemdeki seri portlari (cihaz_adi, aciklama) ciftleri olarak dondurur."""
    ports = []
    for port in sorted(list_ports.comports(), key=lambda p: p.device):
        ports.append((port.device, port.description or ""))
    return ports


def port_from_label(label):
    """Listedeki "COM1  -  aciklama" metninden port adini ayiklar."""
    text = (label or "").strip()
    return text.split("  -")[0].strip() if "  -" in text else text


# --------------------------------------------------------------------------- #
# Sicaklik okuma
# --------------------------------------------------------------------------- #
def _lib_dir():
    """LibreHardwareMonitor DLL klasoru (exe icine paketlenmis halde de bulur)."""
    if getattr(sys, "frozen", False):                   # PyInstaller ile paketli
        packed = os.path.join(getattr(sys, "_MEIPASS", ""), "lib")
        if os.path.isdir(packed):
            return packed
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")


class TemperatureReader:
    """CPU sicakligini okur.

    Once LibreHardwareMonitor kutuphanesiyle gercek sensor denenir; bunun icin
    PawnIO surucusu kurulu olmali ve program yonetici olarak calismalidir.
    Sensor okunamazsa CPU yukune bagli bir model degeri uretilir ve kaynak
    "model" olarak isaretlenir -- boylece verinin olcum olup olmadigi bellidir.
    """

    def __init__(self):
        self.source = "model"
        self.note = ""
        self._model_temp = 40.0
        self._computer = None
        self._temperature_type = None
        try:
            self._open_hardware()
        except Exception as exc:                        # pythonnet/DLL yoksa
            self.note = "donanim sensoru acilamadi (%s)" % type(exc).__name__

    def _open_hardware(self):
        dll = os.path.join(_lib_dir(), "LibreHardwareMonitorLib.dll")
        if not os.path.exists(dll):
            self.note = "LibreHardwareMonitorLib.dll bulunamadi"
            return
        import clr                                      # pythonnet koprusu
        clr.AddReference(dll)
        from LibreHardwareMonitor.Hardware import Computer, SensorType

        computer = Computer()
        computer.IsCpuEnabled = True                    # sadece islemciyi tara
        computer.Open()
        self._computer = computer
        self._temperature_type = SensorType.Temperature

    def _read_hardware(self):
        """Gercek sensor degerini dondurur; okunamazsa None."""
        if self._computer is None:
            return None
        for hardware in self._computer.Hardware:
            hardware.Update()                           # degerleri tazele
            for sensor in hardware.Sensors:
                if sensor.SensorType != self._temperature_type:
                    continue
                if sensor.Value and sensor.Value > 0:   # 0 = surucu/yetki yok
                    self.note = sensor.Name
                    return round(float(sensor.Value), 1)
        self.note = "sensor 0 dondu (yonetici olarak calistirin)"
        return None

    def read(self, cpu_percent):
        """Sicakligi dondurur, kaynagini self.source alanina yazar."""
        value = self._read_hardware()
        if value is not None:
            self.source = "lhm"
            return value

        # Gercek sensor yoksa: yuke bagli, yumusatilmis tahmin degeri.
        target = 35.0 + 0.45 * float(cpu_percent)
        self._model_temp += (target - self._model_temp) * 0.25
        self.source = "model"
        return round(self._model_temp, 1)

    def describe(self):
        """Arayuzde gosterilecek tek satirlik kaynak aciklamasi."""
        if self.source == "lhm":
            return "Sicaklik: donanim sensoru (%s)" % self.note
        return "Sicaklik: OLCUM DEGIL, model degeri - %s" % (self.note or "sensor yok")

    def close(self):
        if self._computer is not None:
            try:
                self._computer.Close()
            except Exception:
                pass
            self._computer = None


def is_admin():
    """Program yonetici yetkisiyle mi calisiyor? (gercek sensor icin gerekli)"""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


# --------------------------------------------------------------------------- #
# Paket bicimi
# --------------------------------------------------------------------------- #
def collect_sample(seq, temp_reader):
    """Tek bir olcum ornegi uretir (sira no, zaman, cpu, bellek, sicaklik)."""
    cpu = psutil.cpu_percent(interval=None)             # bloklamayan okuma
    mem = psutil.virtual_memory().percent
    temp = temp_reader.read(cpu)
    return {
        "seq": seq,
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "cpu": round(float(cpu), 1),
        "mem": round(float(mem), 1),
        "temp": temp,
        "temp_src": temp_reader.source,
    }


def encode(sample):
    """Ornegi seri porta yazilacak baytlara cevirir (JSON + satir sonu)."""
    return (json.dumps(sample) + "\n").encode("utf-8")


def decode(line):
    """Tek satiri ornege cevirir; satir bozuksa None doner."""
    try:
        sample = json.loads(line.decode("utf-8", errors="replace"))
    except (ValueError, AttributeError):
        return None
    if not isinstance(sample, dict) or "cpu" not in sample:
        return None
    return sample


def split_lines(buffer):
    """Bayt tamponunu tam satirlara ayirir.

    Seri port paket degil bayt verir: bir okumada yarim paket de gelebilir,
    iki paket birden de. Tam satirlar dondurulur, yarim kalan kisim geride
    birakilir.

    Donen deger: (tam_satirlar, artan_baytlar)
    """
    parts = buffer.split(b"\n")
    remainder = parts.pop()                 # son parca satir sonu gormedi
    lines = [part.strip() for part in parts if part.strip()]
    return lines, remainder


# --------------------------------------------------------------------------- #
# Esik ustu istatistik
# --------------------------------------------------------------------------- #
MIN_THRESHOLD = 0.0
MAX_THRESHOLD = 100.0


def parse_threshold(text):
    """Kullanicinin yazdigi esik metnini sayiya cevirir.

    Gecerli aralik: 0 - 100 (CPU kullanimi yuzde oldugu icin).
    Sayiya cevrilemeyen ya da aralik disindaki deger icin ValueError firlatir;
    arayuz bu hatayi yakalayip kullaniciyi uyarir ve son gecerli degerde kalir.
    """
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        raise ValueError("Esik bir sayi olmali (ornek: 20 veya 35.5).")
    if value != value:                                  # NaN kontrolu
        raise ValueError("Esik bir sayi olmali (ornek: 20 veya 35.5).")
    if value < MIN_THRESHOLD or value > MAX_THRESHOLD:
        raise ValueError("Esik %g ile %g arasinda olmali."
                         % (MIN_THRESHOLD, MAX_THRESHOLD))
    return value



def threshold_stats(data, threshold):
    """CPU'su esigi asan orneklerin ortalama ve standart sapmasini hesaplar.

    data: {"cpu": [...], "mem": [...], "temp": [...]} -- esit uzunlukta listeler.
    Eksik sicaklik olcumleri None olarak gelir ve hesaba katilmaz.

    Donen sozluk:
      "threshold" esik, "n" secilen ornek sayisi, "total" toplam ornek,
      her alan icin (ortalama, standart_sapma, adet) uclusu.
    """
    cpu_values = data["cpu"]
    selected = [i for i, cpu in enumerate(cpu_values) if cpu > threshold]

    result = {"threshold": threshold, "n": len(selected), "total": len(cpu_values)}
    for field in FIELDS:
        values = [data[field][i] for i in selected if data[field][i] is not None]
        if not values:
            result[field] = (None, None, 0)
        elif len(values) == 1:
            result[field] = (values[0], 0.0, 1)         # tek ornekte sapma yok
        else:
            result[field] = (statistics.mean(values),
                             statistics.stdev(values),   # ornekleme sapmasi (n-1)
                             len(values))
    return result
