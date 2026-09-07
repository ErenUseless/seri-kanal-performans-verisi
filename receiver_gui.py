"""Alici arayuz: seri porttan gelen veriyi kaydeder ve canli grafigini cizer.

Thread kullanilmaz: Tkinter'in after() zamanlayicisi her 200 ms'de portta
bekleyen baytlari okur, tam satirlari ornege cevirir, CSV'ye yazar ve grafigi
yeniler.

Esik: kullanicinin girdigi CPU esiginin ustundeki orneklerin CPU / bellek /
sicaklik ortalama ve standart sapmasi hesaplanip grafige islenir.

Calistirma:  python receiver_gui.py
"""

import csv
import datetime
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure                             # noqa: E402
import serial                                                    # noqa: E402

import common                                                    # noqa: E402

BAUDRATES = ["9600", "19200", "38400", "57600", "115200"]
CSV_HEADER = ["seq", "timestamp", "cpu_percent", "mem_percent",
              "temp_c", "temp_source"]
COLORS = {"cpu": "#d62728", "mem": "#1f77b4", "temp": "#ff7f0e"}
READ_PERIOD_MS = 200          # porttan okuma sikligi


class ReceiverApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.serial_port = None
        self.buffer = b""              # yarim kalan baytlar burada bekler
        self.timer = None

        # Alinan tum veri: grafik ve istatistik icin
        self.times = []                # kacinci saniyede geldi
        self.data = {field: [] for field in common.FIELDS}
        self.received = 0
        self.bad = 0

        self.csv_file = None
        self.csv_writer = None
        self.csv_path = None

        self.threshold_value = 20.0     # son gecerli esik (baslangic degeri)

        self._build_panel()
        self._build_plot()
        self.refresh_ports()

    # ------------------------------------------------------------ arayuz --- #
    def _build_panel(self):
        panel = ttk.Frame(self)
        panel.grid(row=0, column=0, sticky="ns", padx=(0, 8))

        box = ttk.LabelFrame(panel, text="Seri Kanal", padding=8)
        box.pack(fill="x")
        ttk.Label(box, text="Port:").pack(anchor="w")
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(box, textvariable=self.port_var, width=32)
        self.port_box.pack(fill="x", pady=(0, 4))
        ttk.Button(box, text="Portlari Yenile", command=self.refresh_ports).pack(
            fill="x")

        ttk.Label(box, text="Baud:").pack(anchor="w", pady=(6, 0))
        self.baud_var = tk.StringVar(value="115200")
        ttk.Combobox(box, textvariable=self.baud_var, values=BAUDRATES,
                     state="readonly", width=12).pack(anchor="w")

        self.connect_button = ttk.Button(box, text="Baglan", command=self.connect)
        self.connect_button.pack(fill="x", pady=(8, 0))
        self.disconnect_button = ttk.Button(box, text="Kes", command=self.disconnect,
                                            state="disabled")
        self.disconnect_button.pack(fill="x", pady=(4, 0))

        file_box = ttk.LabelFrame(panel, text="Kayit Dosyasi", padding=8)
        file_box.pack(fill="x", pady=(8, 0))
        self.file_var = tk.StringVar(value="(baglaninca otomatik olusur)")
        ttk.Label(file_box, textvariable=self.file_var, wraplength=230,
                  foreground="#555").pack(anchor="w")
        ttk.Button(file_box, text="Dosya Sec...", command=self.choose_file).pack(
            fill="x", pady=(6, 0))

        thr_box = ttk.LabelFrame(panel, text="CPU Esik Degeri", padding=8)
        thr_box.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(thr_box)
        row.pack(fill="x")
        ttk.Label(row, text="Esik (%):").pack(side="left")
        self.threshold_var = tk.StringVar(value="20")
        ttk.Spinbox(row, from_=common.MIN_THRESHOLD, to=common.MAX_THRESHOLD,
                    width=8, textvariable=self.threshold_var,
                    command=self.apply_threshold).pack(side="left", padx=6)
        ttk.Button(row, text="Uygula", command=self.apply_threshold).pack(side="left")

        stats_box = ttk.LabelFrame(panel, text="Esik Ustu Istatistik", padding=8)
        stats_box.pack(fill="x", pady=(8, 0))
        self.stats_text = tk.Text(stats_box, height=8, width=30, wrap="none",
                                  font=("Consolas", 9), state="disabled")
        self.stats_text.pack(fill="x")

        self.status_var = tk.StringVar(value="Hazir.")
        ttk.Label(panel, textvariable=self.status_var, wraplength=240,
                  foreground="#0a5").pack(anchor="w", pady=(8, 0))
        self.count_var = tk.StringVar(value="Alinan: 0   Hatali: 0")
        ttk.Label(panel, textvariable=self.count_var).pack(anchor="w")

    def _build_plot(self):
        self.figure = Figure(figsize=(7.5, 6), dpi=100)
        self.axes = {}
        for index, field in enumerate(common.FIELDS):
            axis = self.figure.add_subplot(3, 1, index + 1)
            axis.set_ylabel(common.FIELD_LABELS[field], fontsize=9)
            axis.grid(alpha=0.3)
            self.axes[field] = axis
        self.axes["temp"].set_xlabel("Gecen sure (s)")
        self.figure.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().grid(row=0, column=1, sticky="nsew")

    def refresh_ports(self):
        ports = common.available_ports()
        self.port_box["values"] = ["%s  -  %s" % (dev, desc) for dev, desc in ports]
        if ports and not self.port_var.get():
            self.port_box.current(0)
        self.status_var.set("%d seri port bulundu." % len(ports))

    # ------------------------------------------------------- baglanti --- #
    def connect(self):
        port_name = common.port_from_label(self.port_var.get())
        if not port_name:
            messagebox.showwarning("Port yok", "Once bir seri port secin.")
            return
        try:
            self.serial_port = serial.Serial(port_name, int(self.baud_var.get()),
                                             timeout=0)
        except serial.SerialException as exc:
            messagebox.showerror("Port acilamadi", str(exc))
            return

        if self.csv_writer is None:
            name = "veri_%s.csv" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.open_csv(os.path.abspath(name))

        self.connect_button["state"] = "disabled"
        self.disconnect_button["state"] = "normal"
        self.status_var.set("Dinleniyor: %s @ %s baud"
                            % (port_name, self.baud_var.get()))
        self.read_once()

    def disconnect(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        if self.serial_port is not None:
            self.serial_port.close()
            self.serial_port = None
        self.connect_button["state"] = "normal"
        self.disconnect_button["state"] = "disabled"
        self.status_var.set("Baglanti kesildi.")

    # ------------------------------------------------------------ veri --- #
    def read_once(self):
        """Portta bekleyen baytlari okur, ornekleri isler, grafigi yeniler."""
        try:
            waiting = self.serial_port.in_waiting
            if waiting:
                self.buffer += self.serial_port.read(waiting)
        except serial.SerialException as exc:
            self.disconnect()
            messagebox.showerror("Okuma hatasi", str(exc))
            return

        lines, self.buffer = common.split_lines(self.buffer)
        for line in lines:
            sample = common.decode(line)
            if sample is None:
                self.bad += 1               # bozuk satir: say ve devam et
            else:
                self.add_sample(sample)

        self.count_var.set("Alinan: %d   Hatali: %d" % (self.received, self.bad))
        if lines:
            self.redraw()
        self.timer = self.after(READ_PERIOD_MS, self.read_once)

    def add_sample(self, sample):
        """Ornegi listeye ekler ve CSV'ye yazar."""
        self.received += 1
        self.times.append(self.received - 1)      # ornek sirasi = zaman ekseni
        for field in common.FIELDS:
            self.data[field].append(sample.get(field))

        if self.csv_writer is not None:
            self.csv_writer.writerow([sample.get("seq"), sample.get("ts"),
                                      sample.get("cpu"), sample.get("mem"),
                                      sample.get("temp"), sample.get("temp_src")])
            self.csv_file.flush()                 # cokme halinde veri kaybolmasin

    # ------------------------------------------------------------ kayit --- #
    def choose_file(self):
        path = filedialog.asksaveasfilename(
            title="Kayit dosyasi", defaultextension=".csv",
            filetypes=[("CSV dosyasi", "*.csv")])
        if path:
            self.open_csv(path)

    def open_csv(self, path):
        self.close_csv()
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        self.csv_file = open(path, "a", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)
        if is_new:
            self.csv_writer.writerow(CSV_HEADER)
        self.csv_path = path
        self.file_var.set(path)

    def close_csv(self):
        if self.csv_file is not None:
            self.csv_file.close()
        self.csv_file = None
        self.csv_writer = None

    # ------------------------------------------------------------ cizim --- #
    def apply_threshold(self):
        """Kutudaki esigi dogrular ve grafigi yeniler.

        Gecersiz deger (harf, negatif sayi, 100'den buyuk) kabul edilmez:
        kullanici uyarilir ve kutu son gecerli degere geri doner.
        """
        try:
            self.threshold_value = common.parse_threshold(self.threshold_var.get())
        except ValueError as exc:
            messagebox.showwarning("Gecersiz esik degeri", str(exc))
            self.threshold_var.set(self._format_threshold())    # eski degere don
            return
        self.threshold_var.set(self._format_threshold())        # "20.0" -> "20"
        self.redraw()

    def _format_threshold(self):
        """Esigi kutuda gosterilecek bicime cevirir (20.0 yerine 20)."""
        value = self.threshold_value
        return str(int(value)) if value == int(value) else str(value)

    def redraw(self):
        """Grafigi ve istatistik panelini yeniden cizer."""
        stats = common.threshold_stats(self.data, self.threshold_value)
        self._update_stats_text(stats)

        for field in common.FIELDS:
            axis = self.axes[field]
            axis.clear()
            axis.grid(alpha=0.3)
            axis.set_ylabel(common.FIELD_LABELS[field], fontsize=9)
            axis.plot(self.times, self.data[field], color=COLORS[field], lw=1.4,
                      label="olcum")

            if field == "cpu":
                axis.axhline(stats["threshold"], color="#444", ls=":",
                             label="esik = %.0f%%" % stats["threshold"])

            mean, std, count = stats[field]
            if count > 0:
                axis.axhline(mean, color="#2ca02c", ls="--",
                             label="ortalama = %.2f" % mean)
                axis.axhspan(mean - std, mean + std, color="#2ca02c", alpha=0.12,
                             label="+/- std = %.2f" % std)
            axis.legend(loc="upper left", fontsize=7)

        self.axes["temp"].set_xlabel("Ornek sirasi")
        self.figure.suptitle("Esigi asan ornek: %d / %d"
                             % (stats["n"], stats["total"]), fontsize=10)
        self.figure.tight_layout(rect=(0, 0, 1, 0.96))
        self.canvas.draw_idle()

    def _update_stats_text(self, stats):
        lines = ["Esik   : CPU > %.0f %%" % stats["threshold"],
                 "Ornek  : %d / %d" % (stats["n"], stats["total"]), ""]
        names = {"cpu": "CPU ", "mem": "RAM ", "temp": "Sic."}
        for field in common.FIELDS:
            mean, std, _ = stats[field]
            if mean is None:
                lines.append("%s ort=  -     std=  -" % names[field])
            else:
                lines.append("%s ort=%6.2f std=%6.2f" % (names[field], mean, std))

        self.stats_text.configure(state="normal")
        self.stats_text.delete("1.0", "end")
        self.stats_text.insert("1.0", "\n".join(lines))
        self.stats_text.configure(state="disabled")

    def on_close(self):
        self.disconnect()
        self.close_csv()
        self.master.destroy()


def main():
    root = tk.Tk()
    root.title("Seri Alici - Kayit ve Canli Grafik")
    root.geometry("1050x700")
    app = ReceiverApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
