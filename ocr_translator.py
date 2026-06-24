import tkinter as tk
from tkinter import messagebox
import threading, subprocess, sys, os

def install(pkg):
    subprocess.check_call([sys.executable,"-m","pip","install",pkg,"--break-system-packages","-q"])

# Check and install deps
missing = []
try: from PIL import Image, ImageGrab, ImageEnhance, ImageFilter
except: missing.append("pillow")

try: import pytesseract
except: missing.append("pytesseract")

try: from deep_translator import GoogleTranslator
except: missing.append("deep-translator")

try: import pyperclip; HAS_CLIP=True
except: HAS_CLIP=False

try: from pynput import keyboard as kb; HAS_PYNPUT=True
except: missing.append("pynput"); HAS_PYNPUT=False

if missing:
    for pkg in missing:
        install(pkg)

from PIL import Image, ImageGrab, ImageEnhance, ImageFilter
import pytesseract
from deep_translator import GoogleTranslator
try: from pynput import keyboard as kb; HAS_PYNPUT=True
except: HAS_PYNPUT=False
try: import pyperclip; HAS_CLIP=True
except: HAS_CLIP=False

# ── Tesseract ──
TESS_OK = False
for p in [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
          r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
          "/usr/bin/tesseract","/usr/local/bin/tesseract"]:
    if os.path.exists(p):
        pytesseract.pytesseract.tesseract_cmd = p
        TESS_OK = True
        break
if not TESS_OK:
    try:
        subprocess.run(["tesseract","--version"],capture_output=True,check=True)
        TESS_OK = True
    except: pass

BG="#0f0f1a"; BG2="#171728"; BG3="#1e1e35"
ACCENT="#6c63ff"; ACCENT2="#a78bfa"
TEXT="#f0efff"; TEXT2="#9090bb"; BORDER="#2e2e50"; SUCCESS="#22c55e"


class SelectionOverlay(tk.Toplevel):
    def __init__(self, master, callback):
        super().__init__(master)
        self.callback = callback
        self.sx = self.sy = 0
        self.rect = None
        self.sw = self.winfo_screenwidth()
        self.sh = self.winfo_screenheight()

        self.overrideredirect(True)
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.35)
        self.configure(bg="black")

        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        sw = self.sw
        self.canvas.create_rectangle(sw//2-230, 14, sw//2+230, 48,
            fill="#0f0f1a", outline=ACCENT, width=1)
        self.canvas.create_text(sw//2, 31,
            text="Виділіть область з текстом   •   ESC — скасувати",
            fill=TEXT2, font=("Segoe UI", 11))

        self.canvas.bind("<ButtonPress-1>",   self._press)
        self.canvas.bind("<B1-Motion>",       self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>", lambda e: self.destroy())

    def _press(self, e): self.sx, self.sy = e.x, e.y

    def _drag(self, e):
        if self.rect: self.canvas.delete(self.rect)
        self.canvas.delete("dim","info")
        x1,y1=min(self.sx,e.x),min(self.sy,e.y)
        x2,y2=max(self.sx,e.x),max(self.sy,e.y)
        for c in [(0,0,self.sw,y1),(0,y1,x1,y2),(x2,y1,self.sw,y2),(0,y2,self.sw,self.sh)]:
            self.canvas.create_rectangle(*c, fill="black", stipple="gray50", tags="dim")
        self.rect = self.canvas.create_rectangle(x1,y1,x2,y2, outline=ACCENT2, width=2)
        self.canvas.create_text(x1+4,y1-10,
            text=f" {abs(x2-x1)}×{abs(y2-y1)} ", fill=ACCENT2,
            anchor="w", font=("Segoe UI",9), tags="info")

    def _release(self, e):
        x1=min(self.sx,e.x); y1=min(self.sy,e.y)
        x2=max(self.sx,e.x); y2=max(self.sy,e.y)
        self.destroy()
        if x2-x1>10 and y2-y1>10:
            self.callback(x1,y1,x2,y2,self.sw,self.sh)


class TranslationPopup(tk.Toplevel):
    def __init__(self, master, ua, en, px, py, sw, sh):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=BORDER)

        outer = tk.Frame(self, bg=ACCENT, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        wrap = tk.Frame(outer, bg=BG)
        wrap.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(wrap, bg=BG2, padx=14, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="✦ Переклад", bg=BG2, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(hdr, text="EN → UA", bg=BG2, fg=TEXT2,
                 font=("Segoe UI", 9)).pack(side="left", padx=8)
        cl = tk.Label(hdr, text="  ✕  ", bg=BG2, fg=TEXT2,
                      font=("Segoe UI", 11), cursor="hand2")
        cl.pack(side="right")
        cl.bind("<Enter>",  lambda e: cl.config(fg="#ff5555", bg="#2a1a1a"))
        cl.bind("<Leave>",  lambda e: cl.config(fg=TEXT2, bg=BG2))
        cl.bind("<Button-1>", lambda e: self.destroy())

        tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x")

        # Body
        body = tk.Frame(wrap, bg=BG, padx=16, pady=14)
        body.pack(fill="both", expand=True)

        wc = len(ua.split())
        wlabel = "слово" if wc==1 else "слова" if 2<=wc<=4 else "слів"
        tk.Label(body, text=f"  {wc} {wlabel}  ", bg=ACCENT, fg="white",
                 font=("Segoe UI", 8, "bold"), pady=2).pack(anchor="w", pady=(0,10))

        h = max(2, min(10, ua.count('\n') + len(ua.split())//30 + 1))
        self.txt = tk.Text(body, font=("Segoe UI", 12), bg=BG, fg=TEXT,
                           relief="flat", bd=0, wrap="word",
                           width=40, height=h,
                           selectbackground=ACCENT, selectforeground="white",
                           cursor="arrow", spacing1=2, spacing2=4, spacing3=2)
        self.txt.pack(fill="both", expand=True)
        self.txt.insert("1.0", ua)
        self.txt.config(state="disabled")

        # Original
        if en:
            tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x")
            orig = tk.Frame(wrap, bg=BG3, padx=14, pady=8)
            orig.pack(fill="x")
            tk.Label(orig, text="ОРИГІНАЛ", bg=BG3, fg=TEXT2,
                     font=("Segoe UI", 7, "bold")).pack(anchor="w")
            ot = tk.Text(orig, font=("Consolas", 9), bg=BG3, fg=TEXT2,
                         relief="flat", bd=0, wrap="word",
                         width=40, height=min(3, en.count('\n')+2), cursor="arrow")
            ot.pack(fill="x")
            ot.insert("1.0", en)
            ot.config(state="disabled")

        # Footer
        tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x")
        ftr = tk.Frame(wrap, bg=BG2, padx=14, pady=8)
        ftr.pack(fill="x")

        self.cb = tk.Label(ftr, text="  📋 Копіювати  ", bg=ACCENT, fg="white",
                           font=("Segoe UI", 9, "bold"), cursor="hand2", pady=4)
        self.cb.pack(side="left")
        self.cb.bind("<Enter>",   lambda e: self.cb.config(bg="#5550dd"))
        self.cb.bind("<Leave>",   lambda e: self.cb.config(bg=ACCENT))
        self.cb.bind("<Button-1>", lambda e: self._copy())
        tk.Label(ftr, text="ESC — закрити", bg=BG2, fg=TEXT2,
                 font=("Segoe UI", 8)).pack(side="right")

        # Position
        self.update_idletasks()
        pw = self.winfo_reqwidth(); ph = self.winfo_reqheight()
        x = max(10, min(px, sw-pw-10))
        y = py+14 if py+14+ph < sh-10 else max(10, py-ph-14)
        self.geometry(f"+{x}+{y}")
        self.bind("<Escape>", lambda e: self.destroy())

        self.attributes("-alpha", 0.0)
        self._fade(0.0)

    def _fade(self, a):
        a = min(a+0.08, 1.0)
        self.attributes("-alpha", a)
        if a < 1.0: self.after(16, lambda: self._fade(a))

    def _copy(self):
        t = self.txt.get("1.0","end").strip()
        if HAS_CLIP: pyperclip.copy(t)
        else: self.clipboard_clear(); self.clipboard_append(t)
        self.cb.config(text="  ✓ Скопійовано  ", bg=SUCCESS)
        self.after(1800, lambda: self.cb.config(text="  📋 Копіювати  ", bg=ACCENT))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OCR EN→UA")
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.resizable(False, False)

        self._popup = None
        self._busy  = False

        self._build_status_window()
        self._setup_hotkey()

    def _build_status_window(self):
        # Small always-on-top status panel
        outer = tk.Frame(self, bg=ACCENT, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill="both", expand=True)

        # Title bar (draggable)
        hdr = tk.Frame(inner, bg=BG2, padx=10, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="✦ OCR Перекладач", bg=BG2, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(hdr, text="EN → UA", bg=BG2, fg=TEXT2,
                 font=("Segoe UI", 8)).pack(side="left", padx=6)
        hdr.bind("<ButtonPress-1>",  self._ds)
        hdr.bind("<B1-Motion>",      self._dm)

        body = tk.Frame(inner, bg=BG, padx=12, pady=10)
        body.pack(fill="both", expand=True)

        # Big capture button
        self.btn = tk.Label(body,
            text="  ~  Виділити текст  ",
            bg=ACCENT, fg="white",
            font=("Segoe UI", 11, "bold"),
            cursor="hand2", pady=8, padx=4)
        self.btn.pack(fill="x", pady=(0,8))
        self.btn.bind("<Enter>",    lambda e: self.btn.config(bg="#5550dd") if not self._busy else None)
        self.btn.bind("<Leave>",    lambda e: self.btn.config(bg=ACCENT) if not self._busy else None)
        self.btn.bind("<Button-1>", lambda e: self._trigger())

        # Status area
        self.status = tk.Label(body, text="Готово", bg=BG, fg=TEXT2,
                               font=("Segoe UI", 8), wraplength=200, justify="left")
        self.status.pack(anchor="w")

        # Diagnostics
        diag = tk.Frame(inner, bg=BG3, padx=10, pady=8)
        diag.pack(fill="x")

        def dot(ok): return ("●", SUCCESS) if ok else ("●", "#ff5555")

        for label, ok in [
            ("Tesseract OCR", TESS_OK),
            ("pynput (гаряча клавіша ~)", HAS_PYNPUT),
            ("Буфер обміну", HAS_CLIP),
        ]:
            row = tk.Frame(diag, bg=BG3)
            row.pack(fill="x", pady=1)
            sym, col = dot(ok)
            tk.Label(row, text=sym, bg=BG3, fg=col,
                     font=("Segoe UI", 8)).pack(side="left")
            tk.Label(row, text=f"  {label}", bg=BG3, fg=TEXT2,
                     font=("Segoe UI", 8)).pack(side="left")

        if not TESS_OK:
            tk.Label(inner,
                text="⚠ Встановіть Tesseract:\ngithub.com/UB-Mannheim/tesseract/wiki",
                bg="#2a1000", fg=WARN,
                font=("Segoe UI", 8), pady=6, padx=10, justify="left").pack(fill="x")

        self.update_idletasks()
        # Center on screen
        w = self.winfo_reqwidth(); h = self.winfo_reqheight()
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        self.geometry(f"+{sw//2-w//2}+{sh//2-h//2}")

    def _ds(self,e): self._dx=e.x_root-self.winfo_x(); self._dy=e.y_root-self.winfo_y()
    def _dm(self,e): self.geometry(f"+{e.x_root-self._dx}+{e.y_root-self._dy}")

    def _setup_hotkey(self):
        if not HAS_PYNPUT: return
        def on_press(key):
            try:
                if hasattr(key,'char') and key.char in ('`','~','ё','Ё'):
                    self.after(0, self._trigger)
            except: pass
        l = kb.Listener(on_press=on_press)
        l.daemon = True
        l.start()

    def _trigger(self):
        if self._busy: return
        if self._popup:
            try: self._popup.destroy()
            except: pass
        SelectionOverlay(self, self._on_select)

    def _on_select(self, x1, y1, x2, y2, sw, sh):
        self._busy = True
        self.btn.config(text="  ⏳ Обробка…  ", bg="#333355")
        self.status.config(text="Розпізнавання тексту…", fg=ACCENT2)
        threading.Thread(target=self._process,
                         args=(x1,y1,x2,y2,x1,y2,sw,sh), daemon=True).start()

    def _process(self, x1, y1, x2, y2, px, py, sw, sh):
        try:
            img = ImageGrab.grab(bbox=(x1,y1,x2,y2))
            w,h = img.size
            scale = max(1, min(4, 800//max(w,1)))
            if scale>1: img = img.resize((w*scale,h*scale), Image.LANCZOS)
            img = img.convert("L")
            img = ImageEnhance.Contrast(img).enhance(2.0)
            img = img.filter(ImageFilter.SHARPEN)

            self.after(0, lambda: self.status.config(text="Переклад…"))
            en = pytesseract.image_to_string(img, config="--oem 3 --psm 6 -l eng").strip()
            en = ' '.join(en.split())

            if not en:
                ua = "⚠  Текст не розпізнано.\n\nСпробуйте виділити більшу область або текст чіткіший."
                en = ""
            else:
                ua = GoogleTranslator(source="en", target="uk").translate(en)
        except Exception as exc:
            ua = f"❌  Помилка:\n{exc}"; en=""

        self.after(0, lambda: self._show(ua, en, px, py, sw, sh))

    def _show(self, ua, en, px, py, sw, sh):
        self._busy = False
        self.btn.config(text="  ~  Виділити текст  ", bg=ACCENT)
        self.status.config(text=f"✓ Перекладено ({len(ua.split())} слів)", fg=SUCCESS)
        self._popup = TranslationPopup(self, ua, en, px, py, sw, sh)

if __name__ == "__main__":
    App().mainloop()
