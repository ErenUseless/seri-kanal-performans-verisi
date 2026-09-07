# Seri Kanal Üzerinden Sistem Performans Verisi

Bilgisayarın zaman, CPU, bellek ve sıcaklık bilgisini seri kanaldan gönderen ve
karşı tarafta kaydedip canlı grafiğini çizen iki masaüstü uygulaması.

Python 3 + Tkinter + pyserial + psutil + matplotlib.

## Dosyalar

| Dosya | Görevi | Satır |
|---|---|---|
| `common.py` | Ortak katman: port listesi, ölçüm toplama, sıcaklık, paket biçimi, istatistik | 247 |
| `sender_gui.py` | Gönderici arayüz | 194 |
| `receiver_gui.py` | Alıcı arayüz: kayıt + canlı grafik + eşik istatistiği | 320 |
| `test_common.py` | 38 test (pytest) | 219 |
| `fetch_lhm.py` | Sıcaklık kütüphanesini nuget.org'dan `lib/` içine indiren yardımcı betik | - |

## Kurulum

**1. Python bağımlılıkları:**

```bash
pip install -r requirements.txt
```

Bu kadarıyla uygulama çalışır. Sıcaklık, gerçek sensör bulunamadığında CPU yüküne
bağlı bir model değeri olarak üretilir ve her kayıtta `temp_src = "model"` şeklinde
işaretlenir, yani verinin ölçüm olup olmadığı her zaman bellidir.

**2. Gerçek CPU sıcaklığı isteniyorsa (isteğe bağlı, yalnızca Windows):**

```bash
python fetch_lhm.py
```

Bu betik LibreHardwareMonitor kütüphanesini ve bağımlılıklarını nuget.org'dan
indirip `lib/` klasörüne yerleştirir. Üçüncü parti ikili dosyalar olduğu için
depoya dahil edilmemişlerdir. Ayrıca [PawnIO](https://pawnio.eu) sürücüsünün
kurulu olması ve gönderici uygulamanın **yönetici olarak** çalıştırılması gerekir;
bu üçü sağlandığında sıcaklık işlemcinin kendi kaydından (Tctl/Tdie) okunur ve
`temp_src = "lhm"` olur.

`lib/` klasörü yoksa ya da `pythonnet` kurulu değilse uygulama hata vermez, sadece
model değerine düşer.

## Sanal seri port çifti

İki uygulamanın haberleşmesi için birbirine bağlı iki COM portu gerekir.
Windows'ta [com0com](https://sourceforge.net/projects/com0com/) veya HHD Virtual
Serial Port Tools ile bir çift oluşturulur (ör. **COM1 ↔ COM2**). Linux/macOS'ta:

```bash
socat -d -d pty,raw,echo=0,link=/tmp/ttyA pty,raw,echo=0,link=/tmp/ttyB
```

## Çalıştırma

Önce alıcıyı bağlayın, sonra göndericiyi başlatın:

```bash
python receiver_gui.py
```

```bash
python sender_gui.py
```

- Alıcıda: port `COM2`, baud `115200` → **Baglan**
- Göndericide: port `COM1`, aynı baud, periyot `1.0` s → **Baslat**

Gerçek CPU sıcaklığı için göndericiyi **yönetici olarak** çalıştırın (sağ tık →
Yönetici olarak çalıştır). Yetki yoksa program çalışmaya devam eder, sadece
sıcaklık model değerine düşer ve arayüz bunu bir uyarıyla bildirir.

## Nasıl çalışıyor

**Paket biçimi.** Her ölçüm tek satırlık JSON, sonunda satır sonu karakteri:

```json
{"seq": 42, "ts": "2026-09-05T12:00:00.123", "cpu": 23.4, "mem": 48.0, "temp": 51.2, "temp_src": "lhm"}
```

Seri port paket değil bayt taşır; satır sonu karakteri paket sınırını belirler.
Alıcı gelen baytları bir buffer'da biriktirir, `split_lines()` tam satırları
ayırır, yarım kalan kısım bir sonraki okumayı bekler.

**Thread yok.** İki uygulama da Tkinter'ın `after()` zamanlayıcısını kullanır:
gönderici her periyotta bir örnek toplayıp porta yazar, alıcı her 200 ms'de
portta bekleyen baytları okur. Saniyede birkaç örnek için bu yeterlidir ve kod
tek bir akışta okunur.

**Sıcaklık.** Önce LibreHardwareMonitor kütüphanesiyle gerçek sensör denenir
(işlemcinin Tctl/Tdie kaydı). Bunun için [PawnIO](https://pawnio.eu) sürücüsü
kurulu olmalı ve program yönetici olarak çalışmalıdır. Okunamazsa CPU yüküne
bağlı bir model değeri üretilir ve `temp_src` alanı `"model"` olur; böylece
verinin ölçüm olup olmadığı her satırda bellidir.

**Kayıt.** Alınan her örnek anında CSV'ye yazılır ve diske işlenir (`flush`), ki
program beklenmedik şekilde kapansa da veri kaybolmasın. Dosya seçilmezse
bağlanma anında `veri_<tarih>.csv` otomatik oluşturulur.
Sütunlar: `seq, timestamp, cpu_percent, mem_percent, temp_c, temp_source`

**Eşik istatistiği.** Kullanıcı bir CPU eşiği girer. CPU'su eşiğin üstünde olan
**tüm örnekler** seçilir; bu örneklerin CPU, bellek ve sıcaklık değerlerinin
ortalaması ve standart sapması (örneklem formülü, n−1) hesaplanır. Grafikte:
CPU ekseninde noktalı eşik çizgisi, her eksende yeşil kesikli ortalama çizgisi
ve ortalama ± standart sapma bandı; yan panelde aynı değerlerin tablosu.
Eşik değiştirilip **Uygula**'ya basılınca veri yeniden toplanmaz, sadece hesap
tekrarlanır.

Eşik girişi doğrulanır: yalnızca 0-100 arasındaki sayılar kabul edilir. Negatif
sayı, 100'den büyük değer ya da sayı olmayan bir metin (`abc`, boş, `12,5`)
girilirse uyarı gösterilir ve kutu son geçerli değere döner, geçersiz giriş
sessizce sıfır sayılmaz.

## Testler

```bash
pytest -v
```

38 test, ~0,1 saniye. Hepsi `common.py` içindeki saf fonksiyonları doğrular:
seri port, ekran ya da yönetici yetkisi gerekmez.

| Konu | Ne doğrulanıyor |
|---|---|
| `encode` / `decode` | Bir örnek tam bir satır olarak kodlanıyor, çözülünce aynen geri geliyor; bozuk satır programı çökertmiyor |
| `split_lines` | Yarım gelen paket bekletiliyor, aynı anda gelen iki paket ayrılıyor |
| `threshold_stats` | Eşik seçimi (`>`, eşite eşit olan seçilmez), ortalama ve n−1 sapma, tek örnek durumu, eşiği aşan yoksa boş sonuç, eksik sıcaklığın hesaba katılmaması |
| `parse_threshold` | Geçerli değerler (0, 100, ondalıklı, boşluklu), negatif ve 100 üstü reddi, harf/boş/virgüllü girişin reddi, hata mesajının açıklayıcı olması |
| Yardımcılar | Port etiketinden cihaz adı çıkarma, port listesinin biçimi |

## Tek dosyalık exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name SeriGonderici --add-data "lib;lib" --collect-all pythonnet --hidden-import clr sender_gui.py
```

```bash
pyinstaller --onefile --windowed --name SeriAlici --add-data "lib;lib" --collect-all pythonnet --hidden-import clr receiver_gui.py
```

Çıktılar `dist/` klasörüne yazılır. Hedef bilgisayarda Python gerekmez; sanal
COM sürücüsü ve (gerçek sıcaklık isteniyorsa) PawnIO gerekir.
