import tkinter as tk
from tkinter import scrolledtext
import threading
import subprocess
import sys
import os

def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--break-system-packages", "-q"])

try:
    from PIL import Image, ImageTk, ImageGrab
except ImportError:
    install("pillow"); from PIL import Image, ImageTk, ImageGrab

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
#  Popup translation window
# ─────────────────────────────────────────────
class TranslationPopup(tk.Toplevel):
    def __init__(self, master, text, x, y):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#1e1e2e")

        # Shadow border frame
        outer = tk.Frame(self, bg="#3a3a5c", padx=1, pady=1)
        outer.pack(fill="both", expand=True)

        inner = tk.Frame(outer, bg="#1e1e2e")
        inner.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(inner, bg="#2a2a42", pady=6, padx=10)
        hdr.pack(fill="x")

        tk.Label(hdr, text="🔍 Переклад EN → UA",
                 bg="#2a2a42", fg="#a0a0cc",
                 font=("Segoe UI", 9)).pack(side="left")

        tk.Button(hdr, text="✕",
                  bg="#2a2a42", fg="#888",
                  font=("Segoe UI", 9), relief="flat",
                  bd=0, cursor="hand2",
                  activebackground="#ff5555",
                  activeforeground="white",
                  command=self.destroy).pack(side="right")

        # Translation text
        self.txt = tk.Text(
            inner,
            font=("Segoe UI", 11),
            bg="#1e1e2e", fg="#e0e0ff",
            relief="flat", bd=0,
            wrap="word",
            padx=12, pady=10,
            cursor="arrow",
            width=40, height=6,
            selectbackground="#3a3a6a",
            selectforeground="white"
        )
        self.txt.pack(fill="both", expand=True, padx=2)
        self.txt.insert("1.0", text)
        self.txt.config(state="disabled")

        # Footer with copy button
        ftr = tk.Frame(inner, bg="#161626", pady=5, padx=10)
        ftr.pack(fill="x")

        self.copy_btn = tk.Button(
            ftr, text="📋 Копіювати",
            bg="#2a2a42", fg="#a0a0cc",
            font=("Segoe UI", 9), relief="flat",
            bd=0, cursor="hand2", padx=8, pady=3,
            activebackground="#3a3a62",
            activeforeground="white",
            command=self._copy
        )
        self.copy_btn.pack(side="left")

        tk.Label(ftr, text="ESC — закрити",
                 bg="#161626", fg="#555",
                 font=("Segoe UI", 8)).pack(side="right")

        # Auto-resize text area based on content
        self.txt.update_idletasks()
        lines = text.count('\n') + 1
        words = len(text.split())
        h = max(4, min(12, lines + words // 35 + 1))
        self.txt.config(height=h)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<FocusOut>", self._on_focus_out)

        # Position popup near selection
        self.update_idletasks()
        pw = self.winfo_reqwidth()
        ph = self.winfo_reqheight()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()

        px = min(x, sw - pw - 10)
        py = min(y + 20, sh - ph - 10)
        self.geometry(f"+{px}+{py}")

        self.focus_force()

    def _on_focus_out(self, e):
        # Don't close if focus went to child widget
        try:
            fw = self.focus_get()
            if fw and (fw == self or str(fw).startswith(str(self))):
                return
        except Exception:
            pass
        # Close after small delay to allow button clicks
        self.after(150, self._check_focus)

    def _check_focus(self):
        try:
            fw = self.focus_get()
            if fw is None or not str(fw).startswith(str(self)):
                self.destroy()
        except Exception:
            self.destroy()

    def _copy(self):
        text = self.txt.get("1.0", "end").strip()
        if HAS_CLIPBOARD:
            pyperclip.copy(text)
        else:
            self.clipboard_clear()
            self.clipboard_append(text)
        self.copy_btn.config(text="✅ Скопійовано")
        self.after(1500, lambda: self.copy_btn.config(text="📋 Копіювати"))


# ─────────────────────────────────────────────
#  Loading popup
# ─────────────────────────────────────────────
class LoadingPopup(tk.Toplevel):
    def __init__(self, master, x, y):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#1e1e2e")

        outer = tk.Frame(self, bg="#3a3a5c", padx=1, pady=1)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="⏳  Розпізнавання і переклад…",
                 bg="#1e1e2e", fg="#a0a0cc",
                 font=("Segoe UI", 10),
                 padx=16, pady=12).pack()

        self.update_idletasks()
        self.geometry(f"+{x}+{y+20}")


# ─────────────────────────────────────────────
#  Full-screen selection overlay
# ─────────────────────────────────────────────
class SelectionOverlay(tk.Toplevel):
    def __init__(self, master, callback):
        super().__init__(master)
        self.callback = callback
        self.start_x = self.start_y = 0
        self.cur_x = self.cur_y = 0
        self.rect = None
        self.dim_rects = []

        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.01)
        self.configure(bg="black")
        self.overrideredirect(True)

        self.canvas = tk.Canvas(self, bg="black",
                                highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        # Hint label
        sw = self.winfo_screenwidth()
        hint = tk.Label(self.canvas,
                        text="  Виділіть область з текстом  •  ESC — скасувати  ",
                        bg="#1e1e2e", fg="#c0c0e0",
                        font=("Segoe UI", 12), pady=8, padx=16,
                        relief="flat")
        hint.place(x=sw//2, y=16, anchor="n")

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Escape>", lambda e: self.destroy())

        # Fade in
        self._alpha = 0.01
        self._fade_in()

    def _fade_in(self):
        self._alpha = min(self._alpha + 0.04, 0.35)
        self.attributes("-alpha", self._alpha)
        if self._alpha < 0.35:
            self.after(20, self._fade_in)

    def _redraw(self, x1, y1, x2, y2):
        self.canvas.delete("dim")
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # Dim everything outside selection
        self.canvas.create_rectangle(0, 0, sw, y1,
            fill="black", stipple="gray50", tags="dim")
        self.canvas.create_rectangle(0, y1, x1, y2,
            fill="black", stipple="gray50", tags="dim")
        self.canvas.create_rectangle(x2, y1, sw, y2,
            fill="black", stipple="gray50", tags="dim")
        self.canvas.create_rectangle(0, y2, sw, sh,
            fill="black", stipple="gray50", tags="dim")
        # Selection border
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="#00d4ff", width=2
        )
        # Size label
        self.canvas.delete("size")
        self.canvas.create_text(
            x1 + 4, y1 - 14,
            text=f"{abs(x2-x1)} × {abs(y2-y1)} px",
            fill="#00d4ff", anchor="w",
            font=("Segoe UI", 9), tags="size"
        )

    def on_press(self, e):
        self.start_x, self.start_y = e.x, e.y

    def on_drag(self, e):
        x1, y1 = min(self.start_x, e.x), min(self.start_y, e.y)
        x2, y2 = max(self.start_x, e.x), max(self.start_y, e.y)
        self._redraw(x1, y1, x2, y2)
        self.cur_x, self.cur_y = e.x, e.y

    def on_release(self, e):
        x1 = min(self.start_x, e.x)
        y1 = min(self.start_y, e.y)
        x2 = max(self.start_x, e.x)
        y2 = max(self.start_y, e.y)
        self.destroy()
        if x2 - x1 > 10 and y2 - y1 > 10:
            self.callback(x1, y1, x2, y2)


# ─────────────────────────────────────────────
#  Tray-like main window (tiny, stays on top)
# ─────────────────────────────────────────────
class OCRTranslatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OCR EN→UA")
        self.geometry("200x54")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(bg="#1e1e2e")
        self.overrideredirect(False)

        self._popup = None
        self._loading = None
        self._tesseract_ok = self._check_tesseract()
        self._build_ui()

        self.bind_all("<Control-Shift-s>", lambda e: self._start_selection())
        self.bind_all("<Control-Shift-S>", lambda e: self._start_selection())

        # Allow dragging window
        self.bind("<ButtonPress-1>", self._drag_start)
        self.bind("<B1-Motion>", self._drag_move)

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
            subprocess.run(["tesseract", "--version"], capture_output=True, check=True)
            return True
        except Exception:
            return False

    def _build_ui(self):
        self.configure(bg="#1e1e2e")

        frame = tk.Frame(self, bg="#1e1e2e")
        frame.pack(fill="both", expand=True, padx=6, pady=6)

        self.btn = tk.Button(
            frame,
            text="🔍  Виділити текст",
            command=self._start_selection,
            bg="#0066cc", fg="white",
            font=("Segoe UI", 10, "bold"),
            relief="flat", bd=0,
            padx=10, pady=6,
            cursor="hand2",
            activebackground="#0052a3",
            activeforeground="white"
        )
        self.btn.pack(side="left", fill="both", expand=True)

        hint = tk.Label(frame, text="Ctrl\n+⇧+S",
                        bg="#1e1e2e", fg="#555",
                        font=("Segoe UI", 7))
        hint.pack(side="right", padx=(4, 0))

        if not self._tesseract_ok:
            self.configure(bg="#3a1a00")
            self.btn.config(text="⚠ Tesseract не знайдено",
                            bg="#cc4400", font=("Segoe UI", 9))

        # Make window draggable via button too
        self.btn.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.btn.bind("<B1-Motion>", self._drag_move, add="+")

    def _drag_start(self, e):
        self._dx = e.x_root - self.winfo_x()
        self._dy = e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _start_selection(self):
        if self._popup:
            try: self._popup.destroy()
            except: pass
        self.withdraw()
        self.after(150, lambda: SelectionOverlay(self, self._on_area_selected))

    def _on_area_selected(self, x1, y1, x2, y2):
        self.deiconify()
        self.btn.config(state="disabled", text="⏳ Обробка…")

        # Show loading popup near selection
        cx = (x1 + x2) // 2 - 150
        cy = y2
        self._loading = LoadingPopup(self, cx, cy)

        threading.Thread(
            target=self._process,
            args=(x1, y1, x2, y2, cx, cy),
            daemon=True
        ).start()

    def _process(self, x1, y1, x2, y2, px, py):
        try:
            img = ImageGrab.grab(bbox=(x1, y1, x2, y2))

            # Upscale for better OCR
            w, h = img.size
            if w < 400:
                img = img.resize((w * 3, h * 3), Image.LANCZOS)
            elif w < 800:
                img = img.resize((w * 2, h * 2), Image.LANCZOS)

            config = "--oem 3 --psm 6"
            text = pytesseract.image_to_string(img, lang="eng", config=config).strip()

            if not text:
                result = "⚠ Текст не розпізнано.\nСпробуйте виділити більшу область або текст чіткіший."
            else:
                translator = GoogleTranslator(source="en", target="uk")
                result = translator.translate(text)

        except Exception as e:
            result = f"❌ Помилка: {e}"

        self.after(0, lambda: self._show_result(result, px, py))

    def _show_result(self, text, px, py):
        # Close loading
        if self._loading:
            try: self._loading.destroy()
            except: pass
            self._loading = None

        self.btn.config(state="normal", text="🔍  Виділити текст")

        # Show translation popup
        self._popup = TranslationPopup(self, text, px, py)

