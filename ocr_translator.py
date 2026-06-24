import tkinter as tk
import threading, subprocess, sys, os

def install(pkg):
    subprocess.check_call([sys.executable,"-m","pip","install",pkg,"--break-system-packages","-q"])

try: from PIL import Image, ImageGrab, ImageEnhance, ImageFilter
except ImportError: install("pillow"); from PIL import Image, ImageGrab, ImageEnhance, ImageFilter

try: import pytesseract
except ImportError: install("pytesseract"); import pytesseract

try: from deep_translator import GoogleTranslator
except ImportError: install("deep-translator"); from deep_translator import GoogleTranslator

try: import pyperclip; HAS_CLIP=True
except ImportError: HAS_CLIP=False

try:
    from pynput import keyboard as kb
    HAS_PYNPUT=True
except ImportError:
    install("pynput")
    try: from pynput import keyboard as kb; HAS_PYNPUT=True
    except: HAS_PYNPUT=False

# ── Tesseract path ──────────────────────────
for p in [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
          r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
          "/usr/bin/tesseract","/usr/local/bin/tesseract"]:
    if os.path.exists(p):
        pytesseract.pytesseract.tesseract_cmd = p
        break

# ── Colors ──────────────────────────────────
BG      = "#0f0f1a"
BG2     = "#171728"
BG3     = "#1e1e35"
ACCENT  = "#6c63ff"
ACCENT2 = "#a78bfa"
TEXT    = "#f0efff"
TEXT2   = "#9090bb"
BORDER  = "#2e2e50"
SUCCESS = "#22c55e"
WARN    = "#f59e0b"


# ════════════════════════════════════════════
#  Beautiful Translation Popup
# ════════════════════════════════════════════
class TranslationPopup(tk.Toplevel):
    def __init__(self, master, ua_text, en_text, sx, sy, sw, sh):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=BORDER)

        # ── Outer glow border ──
        outer = tk.Frame(self, bg=ACCENT, padx=1, pady=1)
        outer.pack(fill="both", expand=True)

        wrap = tk.Frame(outer, bg=BG)
        wrap.pack(fill="both", expand=True)

        # ── Header ──
        hdr = tk.Frame(wrap, bg=BG2, padx=14, pady=10)
        hdr.pack(fill="x")

        # Left: icon + title
        left = tk.Frame(hdr, bg=BG2)
        left.pack(side="left")
        tk.Label(left, text="✦", bg=BG2, fg=ACCENT2,
                 font=("Segoe UI", 12)).pack(side="left", padx=(0,6))
        tk.Label(left, text="Переклад", bg=BG2, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(left, text="EN → UA", bg=BG2, fg=TEXT2,
                 font=("Segoe UI", 9)).pack(side="left", padx=(8,0))

        # Right: close button
        close_btn = tk.Label(hdr, text="  ✕  ", bg=BG2, fg=TEXT2,
                             font=("Segoe UI", 11), cursor="hand2")
        close_btn.pack(side="right")
        close_btn.bind("<Enter>",  lambda e: close_btn.config(fg="#ff5555", bg="#2a1a1a"))
        close_btn.bind("<Leave>",  lambda e: close_btn.config(fg=TEXT2, bg=BG2))
        close_btn.bind("<Button-1>", lambda e: self.destroy())

        # ── Divider ──
        tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x")

        # ── Translation text ──
        body = tk.Frame(wrap, bg=BG, padx=16, pady=14)
        body.pack(fill="both", expand=True)

        # Word count badge
        wc = len(ua_text.split())
        badge_frame = tk.Frame(body, bg=BG)
        badge_frame.pack(fill="x", pady=(0,10))
        tk.Label(badge_frame,
                 text=f"  {wc} {'слово' if wc==1 else 'слова' if 2<=wc<=4 else 'слів'}  ",
                 bg=ACCENT, fg="white",
                 font=("Segoe UI", 8, "bold"),
                 padx=0, pady=2).pack(side="left")

        # Main translation text (clean, no scrollbar if fits)
        lines = ua_text.count('\n') + 1
        words = len(ua_text.split())
        h = max(2, min(10, lines + words//30 + 1))

        self.txt = tk.Text(body,
            font=("Segoe UI", 12),
            bg=BG, fg=TEXT,
            relief="flat", bd=0,
            wrap="word",
            padx=0, pady=4,
            width=38, height=h,
            selectbackground=ACCENT,
            selectforeground="white",
            cursor="arrow",
            spacing1=2, spacing2=4, spacing3=2
        )
        self.txt.pack(fill="both", expand=True)
        self.txt.insert("1.0", ua_text)
        self.txt.config(state="disabled")

        # ── Original text (collapsed, small) ──
        tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x")

        orig_frame = tk.Frame(wrap, bg=BG3, padx=14, pady=8)
        orig_frame.pack(fill="x")

        tk.Label(orig_frame, text="ОРИГІНАЛ", bg=BG3, fg=TEXT2,
                 font=("Segoe UI", 7, "bold")).pack(anchor="w")

        orig_txt = tk.Text(orig_frame,
            font=("Consolas", 9),
            bg=BG3, fg=TEXT2,
            relief="flat", bd=0,
            wrap="word",
            padx=0, pady=2,
            width=38, height=min(3, en_text.count('\n')+2),
            cursor="arrow"
        )
        orig_txt.pack(fill="x")
        orig_txt.insert("1.0", en_text)
        orig_txt.config(state="disabled")

        # ── Footer ──
        tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x")

        ftr = tk.Frame(wrap, bg=BG2, padx=14, pady=8)
        ftr.pack(fill="x")

        self.copy_lbl = tk.Label(ftr,
            text="  📋  Копіювати  ",
            bg=ACCENT, fg="white",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2", padx=4, pady=4)
        self.copy_lbl.pack(side="left")
        self.copy_lbl.bind("<Enter>",  lambda e: self.copy_lbl.config(bg="#5550dd"))
        self.copy_lbl.bind("<Leave>",  lambda e: self.copy_lbl.config(bg=ACCENT))
        self.copy_lbl.bind("<Button-1>", lambda e: self._copy())

        tk.Label(ftr, text="ESC — закрити  •  ~ — нове виділення",
                 bg=BG2, fg=TEXT2,
                 font=("Segoe UI", 8)).pack(side="right")

        # ── Position ──
        self.update_idletasks()
        pw = self.winfo_reqwidth()
        ph = self.winfo_reqheight()

        # Try below selection, else above
        px = max(10, min(sx, sw - pw - 10))
        py = sy + 14
        if py + ph > sh - 10:
            py = max(10, sy - ph - 14)

        self.geometry(f"+{px}+{py}")
        self.bind("<Escape>", lambda e: self.destroy())

        # Subtle fade-in
        self.attributes("-alpha", 0.0)
        self._fade(0.0)

    def _fade(self, a):
        a = min(a + 0.08, 1.0)
        self.attributes("-alpha", a)
        if a < 1.0:
            self.after(16, lambda: self._fade(a))

    def _copy(self):
        t = self.txt.get("1.0","end").strip()
        if HAS_CLIP: pyperclip.copy(t)
        else: self.clipboard_clear(); self.clipboard_append(t)
        self.copy_lbl.config(text="  ✓  Скопійовано  ", bg=SUCCESS)
        self.after(1800, lambda: self.copy_lbl.config(
            text="  📋  Копіювати  ", bg=ACCENT))


# ════════════════════════════════════════════
#  Selection overlay
# ════════════════════════════════════════════
class SelectionOverlay(tk.Toplevel):
    def __init__(self, master, callback):
        super().__init__(master)
        self.callback = callback
        self.sx = self.sy = 0
        self.rect = None

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.sw, self.sh = sw, sh

        self.overrideredirect(True)
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.35)
        self.configure(bg="black")

        self.canvas = tk.Canvas(self, bg="black",
                                highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        # Hint
        self.canvas.create_rectangle(sw//2-210, 14, sw//2+210, 48,
            fill="#0f0f1a", outline=ACCENT, width=1)
        self.canvas.create_text(sw//2, 31,
            text="Виділіть область з текстом   •   ESC — скасувати",
            fill=TEXT2, font=("Segoe UI", 11))

        self.canvas.bind("<ButtonPress-1>",   self._press)
        self.canvas.bind("<B1-Motion>",       self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>", lambda e: self.destroy())

    def _press(self, e):
        self.sx, self.sy = e.x, e.y

    def _drag(self, e):
        if self.rect: self.canvas.delete(self.rect)
        self.canvas.delete("info")
        x1,y1 = min(self.sx,e.x), min(self.sy,e.y)
        x2,y2 = max(self.sx,e.x), max(self.sy,e.y)
        # Dim overlay rects
        self.canvas.delete("dim")
        for coords in [(0,0,self.sw,y1),(0,y1,x1,y2),
                       (x2,y1,self.sw,y2),(0,y2,self.sw,self.sh)]:
            self.canvas.create_rectangle(*coords,
                fill="black", stipple="gray50", tags="dim")
        # Selection box
        self.rect = self.canvas.create_rectangle(
            x1,y1,x2,y2, outline=ACCENT2, width=2)
        # Size label
        self.canvas.create_text(x1+4, y1-10,
            text=f" {abs(x2-x1)}×{abs(y2-y1)} ",
            fill=ACCENT2, anchor="w",
            font=("Segoe UI", 9), tags="info")

    def _release(self, e):
        x1=min(self.sx,e.x); y1=min(self.sy,e.y)
        x2=max(self.sx,e.x); y2=max(self.sy,e.y)
        self.destroy()
        if x2-x1>10 and y2-y1>10:
            self.callback(x1,y1,x2,y2, self.sw, self.sh)


# ════════════════════════════════════════════
#  Loading popup
# ════════════════════════════════════════════
class LoadingPopup(tk.Toplevel):
    def __init__(self, master, x, y):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.92)
        self.configure(bg=BORDER)

        f = tk.Frame(self, bg=ACCENT, padx=1, pady=1)
        f.pack()
        inner = tk.Frame(f, bg=BG2, padx=20, pady=14)
        inner.pack()

        self._dots = 0
        self.lbl = tk.Label(inner, text="⏳  Розпізнавання…",
                            bg=BG2, fg=TEXT,
                            font=("Segoe UI", 11))
        self.lbl.pack()
        tk.Label(inner, text="Зачекайте секунду",
                 bg=BG2, fg=TEXT2,
                 font=("Segoe UI", 9)).pack()

        self.update_idletasks()
        self.geometry(f"+{x}+{y}")
        self._animate()

    def _animate(self):
        try:
            stages = ["⏳  Розпізнавання…","🔤  Аналіз тексту…","🌐  Переклад…"]
            self._dots = (self._dots+1) % len(stages)
            self.lbl.config(text=stages[self._dots])
            self.after(700, self._animate)
        except: pass


# ════════════════════════════════════════════
#  Main app (hidden root)
# ════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()   # completely hidden
        self.title("OCR Translator")
        self._popup   = None
        self._loading = None
        self._overlay_open = False

        self._setup_hotkey()
        # Fallback: also bind to root
        self.bind_all("<grave>", lambda e: self._trigger())  # ` key fallback

    def _setup_hotkey(self):
        if not HAS_PYNPUT:
            # Fallback — show a small helper window
            self._show_fallback_window()
            return
        def on_press(key):
            try:
                if hasattr(key,'char') and key.char == '`':
                    self.after(0, self._trigger)
            except: pass
        listener = kb.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()

    def _show_fallback_window(self):
        """Tiny floating button if pynput unavailable"""
        self.deiconify()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=BG)
        self.geometry("180x44+20+20")

        f = tk.Frame(self, bg=ACCENT, padx=1, pady=1)
        f.pack(fill="both", expand=True)
        btn = tk.Label(f, text="  🔍  Виділити текст  ",
                       bg=BG2, fg=TEXT,
                       font=("Segoe UI", 10, "bold"),
                       cursor="hand2", pady=8)
        btn.pack(fill="both", expand=True)
        btn.bind("<Button-1>", lambda e: self._trigger())
        # Drag
        btn.bind("<ButtonPress-1>",  self._ds)
        btn.bind("<B1-Motion>",      self._dm)

    def _ds(self,e): self._dx=e.x_root-self.winfo_x(); self._dy=e.y_root-self.winfo_y()
    def _dm(self,e): self.geometry(f"+{e.x_root-self._dx}+{e.y_root-self._dy}")

    def _trigger(self):
        if self._overlay_open: return
        if self._popup:
            try: self._popup.destroy()
            except: pass
        self._overlay_open = True
        self.after(100, lambda: SelectionOverlay(self, self._on_select))

    def _on_select(self, x1, y1, x2, y2, sw, sh):
        self._overlay_open = False
        cx = (x1+x2)//2 - 140
        cy = y2 + 10
        self._loading = LoadingPopup(self, cx, cy)
        threading.Thread(target=self._process,
                         args=(x1,y1,x2,y2,x1,y2,sw,sh), daemon=True).start()

    def _process(self, x1, y1, x2, y2, px, py, sw, sh):
        try:
            img = ImageGrab.grab(bbox=(x1,y1,x2,y2))
            # Upscale + enhance for better OCR
            w,h = img.size
            scale = max(1, min(4, 800//max(w,1)))
            if scale > 1:
                img = img.resize((w*scale, h*scale), Image.LANCZOS)
            img = img.convert("L")
            img = ImageEnhance.Contrast(img).enhance(2.0)
            img = img.filter(ImageFilter.SHARPEN)

            cfg = "--oem 3 --psm 6 -l eng"
            en = pytesseract.image_to_string(img, config=cfg).strip()
            en = ' '.join(en.split())  # normalize whitespace

            if not en:
                ua = "⚠  Текст не розпізнано.\n\nСпробуйте виділити більшу область або перевірте чіткість тексту."
                en  = ""
            else:
                ua = GoogleTranslator(source="en", target="uk").translate(en)
        except Exception as exc:
            ua = f"❌  Помилка:\n{exc}"
            en = ""

        self.after(0, lambda: self._show(ua, en, px, py, sw, sh))

    def _show(self, ua, en, px, py, sw, sh):
        if self._loading:
            try: self._loading.destroy()
            except: pass
        self._popup = TranslationPopup(self, ua, en, px, py, sw, sh)

if __name__ == "__main__":
    app = App()
    app.mainloop()
