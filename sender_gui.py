"""Gonderici arayuz: sistem verilerini toplayip seri porttan gonderir.

Thread kullanilmaz. Tkinter'in kendi zamanlayicisi (after) ile belirli
araliklarla ornek toplanir ve porta yazilir; saniyede birkac ornekte bu
yeterlidir ve kod tek bir akista okunur.

Calistirma:  python sender_gui.py
"""

import tkinter as tk
from tkinter import messagebox, ttk

import serial

import common

BAUDRATES = ["9600", "19200", "38400", "57600", "115200"]


class SenderApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=10)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)

        self.serial_port = None          # acik port (yoksa None)
        self.temp_reader = None          # sicaklik okuyucu
        self.seq = 0                     # gonderilen paket sayaci
        self.timer = None                # after() zamanlayici kimligi

        self._build_widgets()
        self.refresh_ports()

    # ------------------------------------------------------------ arayuz --- #
    def _build_widgets(self):
        # -- Seri kanal ayarlari --
        box = ttk.LabelFrame(self, text="Seri Kanal", padding=8)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Port:").grid(row=0, column=0, sticky="w")
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(box, textvariable=self.port_var, width=42)
        self.port_box.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(box, text="Portlari Yenile", command=self.refresh_ports).grid(
            row=0, column=2)

        ttk.Label(box, text="Baud:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.baud_var = tk.StringVar(value="115200")
        ttk.Combobox(box, textvariable=self.baud_var, values=BAUDRATES,
                     state="readonly", width=12).grid(
            row=1, column=1, sticky="w", padx=4, pady=(6, 0))

        ttk.Label(box, text="Periyot (saniye):").grid(
            row=2, column=0, sticky="w", pady=(6, 0))
        self.period_var = tk.StringVar(value="1.0")
        ttk.Spinbox(box, from_=0.1, to=60.0, increment=0.1, width=10,
                    textvariable=self.period_var).grid(
            row=2, column=1, sticky="w", padx=4, pady=(6, 0))

        buttons = ttk.Frame(box)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.start_button = ttk.Button(buttons, text="Baslat", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="Durdur", command=self.stop,
                                      state="disabled")
        self.stop_button.pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="Hazir.")
        ttk.Label(box, textvariable=self.status_var, foreground="#0a5").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        # Yonetici uyarisi: gercek sicaklik sensoru yonetici yetkisi ister.
        admin_text = ("Yonetici yetkisi var: gercek sicaklik sensoru okunabilir."
                      if common.is_admin() else
                      "UYARI: Program yonetici olarak calistirilmadi. Gercek CPU "
                      "sicakligi okunamaz, model degeri gonderilir.")
        ttk.Label(box, text=admin_text, wraplength=560, justify="left",
                  foreground="#0a5" if common.is_admin() else "#b45309").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # -- Anlik degerler --
        values = ttk.LabelFrame(self, text="Anlik Degerler", padding=8)
        values.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.value_vars = {}
        rows = [("ts", "Zaman"), ("cpu", "CPU (%)"), ("mem", "Bellek (%)"),
                ("temp", "Sicaklik (C)"), ("temp_src", "Sicaklik kaynagi"),
                ("seq", "Gonderilen paket")]
        for row, (key, label) in enumerate(rows):
            ttk.Label(values, text=label + ":").grid(row=row, column=0, sticky="w")
            var = tk.StringVar(value="-")
            ttk.Label(values, textvariable=var,
                      font=("Consolas", 10, "bold")).grid(
                row=row, column=1, sticky="w", padx=8)
            self.value_vars[key] = var

    def refresh_ports(self):
        """Port listesini yeniden tarar."""
        ports = common.available_ports()
        self.port_box["values"] = ["%s  -  %s" % (dev, desc) for dev, desc in ports]
        if ports and not self.port_var.get():
            self.port_box.current(0)
        self.status_var.set("%d seri port bulundu." % len(ports))

    # ------------------------------------------------------------- eylem --- #
    def start(self):
        """Portu acar ve periyodik gonderimi baslatir."""
        port_name = common.port_from_label(self.port_var.get())
        if not port_name:
            messagebox.showwarning("Port yok", "Once bir seri port secin.")
            return
        try:
            period = float(self.period_var.get())
            if period <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Gecersiz periyot",
                                   "Periyot pozitif bir sayi olmali.")
            return

        try:
            self.serial_port = serial.Serial(port_name, int(self.baud_var.get()),
                                             timeout=1)
        except serial.SerialException as exc:
            messagebox.showerror("Port acilamadi", str(exc))
            return

        self.temp_reader = common.TemperatureReader()
        self.seq = 0
        self.period_ms = int(period * 1000)
        self.start_button["state"] = "disabled"
        self.stop_button["state"] = "normal"
        self.status_var.set("Gonderiliyor: %s @ %s baud"
                            % (port_name, self.baud_var.get()))
        self.send_once()                        # ilk ornegi hemen gonder

    def send_once(self):
        """Bir ornek toplar, porta yazar ve bir sonrakini zamanlar."""
        sample = common.collect_sample(self.seq + 1, self.temp_reader)
        try:
            self.serial_port.write(common.encode(sample))
        except serial.SerialException as exc:
            self.stop()
            messagebox.showerror("Yazma hatasi", str(exc))
            return

        self.seq += 1
        self._show(sample)
        if self.seq == 1:                       # kaynak ilk ornekte bellidir
            self.status_var.set(self.temp_reader.describe())

        self.timer = self.after(self.period_ms, self.send_once)

    def _show(self, sample):
        """Anlik degerler kutusunu gunceller."""
        self.value_vars["ts"].set(sample["ts"])
        self.value_vars["cpu"].set("%.1f" % sample["cpu"])
        self.value_vars["mem"].set("%.1f" % sample["mem"])
        self.value_vars["temp"].set("%.1f" % sample["temp"])
        self.value_vars["temp_src"].set(sample["temp_src"])
        self.value_vars["seq"].set(str(sample["seq"]))

    def stop(self):
        """Zamanlayiciyi durdurur, portu ve sicaklik okuyucuyu kapatir."""
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        if self.serial_port is not None:
            self.serial_port.close()
            self.serial_port = None
        if self.temp_reader is not None:
            self.temp_reader.close()
            self.temp_reader = None
        self.start_button["state"] = "normal"
        self.stop_button["state"] = "disabled"
        self.status_var.set("Durduruldu.")

    def on_close(self):
        self.stop()
        self.master.destroy()


def main():
    root = tk.Tk()
    root.title("Seri Gonderici - Sistem Performans Verisi")
    root.geometry("640x460")
    app = SenderApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
