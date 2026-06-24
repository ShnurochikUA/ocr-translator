import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import subprocess
import sys
import os

# --- Auto-install missing packages ---
def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--break-system-packages", "-q"])

try:
    from PIL import Image, ImageTk, ImageGrab, ImageDraw
except ImportError:
    install("pillow"); from PIL import Image, ImageTk, ImageGrab, ImageDraw

try:
    import pytesseract
except ImportError:
    install("pytesseract"); import pytesseract

try:
    from deep_translator import GoogleTranslator
except ImportError:
    install("deep-translator"); from deep_translator import GoogleTranslator

try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False


# ─────────────────────────────────────────────
#  Overlay window for area selection
# ─────────────────────────────────────────────
class SelectionOverlay(tk.Toplevel):
    def __init__(self, master, callback):
        super().__init__(master)
        self.callback = callback
        self.start_x = self.start_y = 0
        self.rect = None

        self.attributes("-fullscreen", True)
        self.attributes("-alpha", 0.25)
        self.attributes("-topmost", True)
        self.configure(bg="black", cursor="crosshair")
        self.overrideredirect(True)

        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        lbl = tk.Label(self.canvas, text="Виділіть область з текстом  •  ESC — скасувати",
                       bg="#1a1a2e", fg="white", font=("Segoe UI", 14), pady=8, padx=16)
        lbl.place(relx=0.5, rely=0.02, anchor="n")

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Escape>", lambda e: self.destroy())

    def on_press(self, e):
        self.start_x, self.start_y = e.x, e.y
        if self.rect:
            self.canvas.delete(self.rect)

    def on_drag(self, e):
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, e.x, e.y,
            outline="#00d4ff", width=2, dash=(4, 2)
        )

    def on_release(self, e):
        x1, y1 = min(self.start_x, e.x), min(self.start_y, e.y)
        x2, y2 = max(self.start_x, e.x), max(self.start_y, e.y)
        self.destroy()
        if x2 - x1 > 10 and y2 - y1 > 10:
            self.callback(x1, y1, x2, y2)


# ─────────────────────────────────────────────
#  Main application window
# ─────────────────────────────────────────────
class OCRTranslatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OCR Перекладач EN → UA")
        self.geometry("680x620")
        self.minsize(500, 500)
        self.configure(bg="#f0f2f5")
        self.resizable(True, True)

        self._tesseract_ok = self._check_tesseract()
        self._build_ui()

        # Hotkey: Ctrl+Shift+S
        self.bind_all("<Control-Shift-s>", lambda e: self._start_selection())
        self.bind_all("<Control-Shift-S>", lambda e: self._start_selection())

    # ── Tesseract check ──────────────────────
    def _check_tesseract(self):
        paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
        ]
        for p in paths:
            if os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                return True
        try:
            subprocess.run(["tesseract", "--version"],
                           capture_output=True, check=True)
            return True
        except Exception:
            return False

    # ── UI ──────────────────────────────────
    def _build_ui(self):
        # ── Header ──
        hdr = tk.Frame(self, bg="#1a1a2e", height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🔍 OCR Перекладач  EN → UA",
                 bg="#1a1a2e", fg="white",
                 font=("Segoe UI", 14, "bold")).pack(side="left", padx=16, pady=12)
        tk.Label(hdr, text="Ctrl+Shift+S",
                 bg="#2d2d44", fg="#aaaacc",
                 font=("Segoe UI", 10), padx=8, pady=2,
                 relief="flat", bd=0).pack(side="right", padx=16, pady=16)

        # ── Tesseract warning ──
        if not self._tesseract_ok:
            warn = tk.Frame(self, bg="#fff3cd")
            warn.pack(fill="x")
            msg = ("⚠  Tesseract не знайдено!  "
                   "Встановіть: https://github.com/UB-Mannheim/tesseract/wiki  "
                   "(Windows) або  sudo apt install tesseract-ocr tesseract-ocr-eng  (Linux)")
            tk.Label(warn, text=msg, bg="#fff3cd", fg="#856404",
                     font=("Segoe UI", 9), wraplength=640,
                     justify="left", padx=12, pady=6).pack(anchor="w")

        # ── Main content ──
        body = tk.Frame(self, bg="#f0f2f5")
        body.pack(fill="both", expand=True, padx=16, pady=12)

        # Capture button
        btn_frame = tk.Frame(body, bg="#f0f2f5")
        btn_frame.pack(fill="x", pady=(0, 12))

        self.btn_capture = tk.Button(
            btn_frame,
            text="📷  Зробити скріншот і перекласти",
            command=self._start_selection,
            bg="#0066cc", fg="white",
            font=("Segoe UI", 12, "bold"),
            relief="flat", bd=0,
            padx=20, pady=10,
            cursor="hand2",
            activebackground="#0052a3",
            activeforeground="white"
        )
        self.btn_capture.pack(side="left")

        self.btn_copy = tk.Button(
            btn_frame,
            text="📋  Копіювати",
            command=self._copy_translation,
            bg="#e8e8e8", fg="#333",
            font=("Segoe UI", 11),
            relief="flat", bd=0,
            padx=14, pady=10,
            cursor="hand2",
            state="disabled"
        )
        self.btn_copy.pack(side="left", padx=(8, 0))

        # Status bar
        self.status_var = tk.StringVar(value="Готово. Натисніть кнопку або Ctrl+Shift+S")
        self.status_lbl = tk.Label(body, textvariable=self.status_var,
                                   bg="#f0f2f5", fg="#555",
                                   font=("Segoe UI", 9), anchor="w")
        self.status_lbl.pack(fill="x", pady=(0, 8))

        # Progress bar
        self.progress = ttk.Progressbar(body, mode="indeterminate", length=200)

        # ── Panels side by side ──
        panels = tk.Frame(body, bg="#f0f2f5")
        panels.pack(fill="both", expand=True)
        panels.columnconfigure(0, weight=1)
        panels.columnconfigure(1, weight=1)
        panels.rowconfigure(1, weight=1)

        tk.Label(panels, text="Розпізнаний текст (EN)",
                 bg="#f0f2f5", fg="#333",
                 font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0,4))
        tk.Label(panels, text="Переклад (UA)",
                 bg="#f0f2f5", fg="#333",
                 font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", padx=(4,0))

        self.txt_ocr = scrolledtext.ScrolledText(
            panels, font=("Consolas", 10), wrap="word",
            bg="white", fg="#222", relief="flat",
            borderwidth=1, highlightbackground="#ccc",
            highlightthickness=1, state="disabled"
        )
        self.txt_ocr.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(4, 0))

        self.txt_trans = scrolledtext.ScrolledText(
            panels, font=("Segoe UI", 10), wrap="word",
            bg="white", fg="#111", relief="flat",
            borderwidth=1, highlightbackground="#ccc",
            highlightthickness=1, state="disabled"
        )
        self.txt_trans.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(4, 0))

        # Preview
        preview_row = tk.Frame(body, bg="#f0f2f5")
        preview_row.pack(fill="x", pady=(10, 0))
        tk.Label(preview_row, text="Скріншот:",
                 bg="#f0f2f5", fg="#555",
                 font=("Segoe UI", 9)).pack(side="left")
        self.preview_lbl = tk.Label(preview_row, bg="#dde", text="(ще немає)",
                                    fg="#888", font=("Segoe UI", 9),
                                    relief="flat", cursor="hand2")
        self.preview_lbl.pack(side="left", padx=(6, 0))

    # ── Actions ─────────────────────────────
    def _start_selection(self):
        self.withdraw()
        self.after(200, lambda: SelectionOverlay(self, self._on_area_selected))

    def _on_area_selected(self, x1, y1, x2, y2):
        self.deiconify()
        self._set_status("Захоплення скріншоту…", busy=True)
        threading.Thread(target=self._process, args=(x1, y1, x2, y2), daemon=True).start()

    def _process(self, x1, y1, x2, y2):
        try:
            # Screenshot
            img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            self._show_preview(img)

            # OCR
            self._set_status("Розпізнавання тексту (OCR)…", busy=True)
            config = "--oem 3 --psm 6"
            text = pytesseract.image_to_string(img, lang="eng", config=config).strip()
            if not text:
                self._set_status("⚠  Текст не розпізнано. Спробуйте більшу область.", busy=False)
                return

            self._set_text(self.txt_ocr, text)

            # Translate
            self._set_status("Переклад…", busy=True)
            translator = GoogleTranslator(source="en", target="uk")
            translated = translator.translate(text)
            self._set_text(self.txt_trans, translated)

            self._set_status(f"✅ Готово! Розпізнано {len(text.split())} слів.", busy=False)
            self.after(0, lambda: self.btn_copy.config(state="normal"))

        except Exception as e:
            self._set_status(f"❌ Помилка: {e}", busy=False)

    def _set_text(self, widget, text):
        def _do():
            widget.config(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.config(state="disabled")
        self.after(0, _do)

    def _show_preview(self, img):
        try:
            thumb = img.copy()
            thumb.thumbnail((220, 80))
            photo = ImageTk.PhotoImage(thumb)
            def _do():
                self.preview_lbl.config(image=photo, text="")
                self.preview_lbl.image = photo
            self.after(0, _do)
        except Exception:
            pass

    def _set_status(self, msg, busy=False):
        def _do():
            self.status_var.set(msg)
            if busy:
                self.progress.pack(fill="x", pady=(0, 4))
                self.progress.start(12)
                self.btn_capture.config(state="disabled")
            else:
                self.progress.stop()
                self.progress.pack_forget()
                self.btn_capture.config(state="normal")
        self.after(0, _do)

    def _copy_translation(self):
        text = self.txt_trans.get("1.0", "end").strip()
        if not text:
            return
        if HAS_CLIPBOARD:
            pyperclip.copy(text)
        else:
            self.clipboard_clear()
            self.clipboard_append(text)
        self.btn_copy.config(text="✅ Скопійовано!")
        self.after(2000, lambda: self.btn_copy.config(text="📋  Копіювати"))


if __name__ == "__main__":
    app = OCRTranslatorApp()
    app.mainloop()
