import ctypes
import ctypes.wintypes
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from urllib.parse import quote
from urllib.request import Request, urlopen

from PIL import ImageEnhance, ImageFilter, ImageGrab, ImageOps, ImageTk


APP_NAME = "Screen Translator UK"
HOTKEY_ID = 0x554B
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
VK_T = 0x54
WM_HOTKEY = 0x0312
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


@dataclass
class TextBlock:
    text: str
    role: str = "paragraph"


LIST_MARKER_RE = re.compile(r"^\s*(?:[•*·\-–—]|\d+[.)])\s+")


def virtual_screen_rect() -> tuple[int, int, int, int]:
    if sys.platform != "win32":
        return (0, 0, 0, 0)
    user32 = ctypes.windll.user32
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return x, y, width, height


def window_geometry(width: int, height: int, x: int, y: int) -> str:
    return f"{width}x{height}{x:+d}{y:+d}"


def config_path() -> Path:
    root = Path(os.getenv("APPDATA") or Path.home())
    return root / APP_NAME / "settings.json"


def load_settings() -> dict:
    defaults = {
        "font_size": 15,
        "theme": "light",
        "last_regions": [],
        "window_geometry": "660x470+80+80",
        "translate_engine": "google",
        "style_mode": "readable",
        "result_view": "popup",
        "libretranslate_url": "",
        "libretranslate_key": "",
    }
    path = config_path()
    if path.exists():
        try:
            defaults.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return defaults


def save_settings(settings: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def find_tesseract() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def clean_english_ocr_blocks(text: str) -> list[TextBlock]:
    text = text.replace("\r", "\n")
    text = re.sub(r"[“”]", '"', text)
    text = re.sub(r"[’`]", "'", text)
    text = re.sub(r"[—–]", "-", text)
    text = re.sub(r"(?m)^\s*[•·]\s*", "- ", text)
    text = re.sub(r"[|¦]", "I", text)
    text = re.sub(
        r"\b[Il1]\b(?=\s+(am|was|were|have|had|will|would|want|wanted|arrived|visited|feel|felt|"
        r"finally|also|already|can|could|should|just|really|think|hope|decided|spent)\b)",
        "I",
        text,
        flags=re.IGNORECASE,
    )

    raw_lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        line = line.strip("_")
        if not line:
            raw_lines.append("")
            continue
        greeting_inside = re.search(r"\b(Hi|Hello|Dear)\b[, ].+", line)
        if greeting_inside and greeting_inside.start() > 8:
            before = line[: greeting_inside.start()].strip(" -")
            after = line[greeting_inside.start() :].strip()
            if before:
                raw_lines.append(before)
            raw_lines.append(after)
        else:
            raw_lines.append(line)

    blocks = []
    current = []
    for index, line in enumerate(raw_lines):
        if not line:
            if current:
                blocks.append(TextBlock(" ".join(current), "paragraph"))
                current = []
            continue
        is_list_item = bool(LIST_MARKER_RE.match(line))
        is_greeting = bool(re.match(r"^(Hi|Hello|Dear)\b", line, flags=re.IGNORECASE))
        is_heading = (
            index <= 2
            and not current
            and len(line) <= 70
            and not re.search(r"[.!?]$", line)
            and len(line.split()) <= 7
        )
        is_short_feature_title = (
            not current
            and len(line) <= 72
            and 3 <= len(line.split()) <= 9
            and not re.search(r"[.!?:]$", line)
            and sum(1 for word in line.split() if word[:1].isupper()) >= 2
        )
        if is_list_item:
            if current:
                blocks.append(TextBlock(" ".join(current), "paragraph"))
                current = []
            blocks.append(TextBlock(LIST_MARKER_RE.sub("", line).strip(), "list"))
            continue
        if is_short_feature_title:
            if current:
                blocks.append(TextBlock(" ".join(current), "paragraph"))
                current = []
            blocks.append(TextBlock(line, "subheading"))
            continue
        if is_heading or is_greeting:
            if current:
                blocks.append(TextBlock(" ".join(current), "paragraph"))
                current = []
            blocks.append(TextBlock(line, "greeting" if is_greeting else "heading"))
            continue
        if current and current[-1].endswith("-"):
            current[-1] = current[-1][:-1] + line
        else:
            current.append(line)
    if current:
        blocks.append(TextBlock(" ".join(current), "paragraph"))

    cleaned_blocks = []
    for block in blocks:
        cleaned = re.sub(r"\s+", " ", block.text).strip()
        cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
        cleaned = re.sub(r"([.!?])(?=[A-Z])", r"\1 ", cleaned)
        if cleaned:
            cleaned_blocks.append(TextBlock(cleaned, block.role))
    return cleaned_blocks


def clean_english_ocr(text: str) -> str:
    blocks = clean_english_ocr_blocks(text)
    return "\n\n".join(block.text for block in blocks).strip()


def split_readable_chunks(text: str, max_chars: int = 900) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks = []
    for paragraph in paragraphs:
        parts = re.split(r"(?<=[.!?])\s+", paragraph)
        buffer = ""
        for part in parts:
            part = part.strip()
            if not part:
                continue
            candidate = f"{buffer} {part}".strip()
            if buffer and len(candidate) > max_chars:
                chunks.append(buffer)
                buffer = part
            else:
                buffer = candidate
        if buffer:
            chunks.append(buffer)
    return chunks or [text.strip()]


def polish_ukrainian_text(text: str) -> str:
    text = text.replace("|", "І")
    text = text.replace("_", "")
    text = re.sub(r"§\s*\d+\s*§", "", text)
    text = re.sub(r"\bI(?=\s+[а-яіїєґА-ЯІЇЄҐ])", "Я", text)
    replacements = {
        "Натисніть довіру": "Порушення довіри",
        "порушення довіри": "Порушення довіри",
        "Новий Единбург": "Новий Единбург",
        "голосування": "голос",
        "безкоштовне оновлення контенту": "безкоштовне оновлення",
        "спрощена версія": "спрощена версія",
        "доступний зараз": "вже доступне",
        "доступна зараз": "вже доступна",
        "випущений трейлер": "релізний трейлер",
        "причеп": "трейлер",
        "Рибальський центр": "Рибальський хаб",
        "Будівельник Утопії": "Utopia Builder",
    }
    for wrong, right in replacements.items():
        text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"(?<!\n)\s+(Привіт[,!])", r"\n\1", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = []
    for block in text.split("\n\n"):
        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", block) if sentence.strip()]
        if not sentences:
            continue
        if len(sentences) == 1 and len(sentences[0]) <= 70:
            sentence = sentences[0]
            lines.append(sentence[0].upper() + sentence[1:] if sentence else sentence)
            continue
        group = []
        for sentence in sentences:
            sentence = sentence[0].upper() + sentence[1:] if sentence else sentence
            group.append(sentence)
            if len(group) == 3:
                lines.append(" ".join(group))
                group = []
        if group:
            lines.append(" ".join(group))
    return "\n".join(lines).strip()


def polish_translated_block(text: str, role: str = "paragraph") -> str:
    text = polish_ukrainian_text(text)
    if role == "heading":
        return text.replace("\n", " ").strip()
    if role == "subheading":
        return text.replace("\n", " ").strip()
    if role == "greeting":
        return text.replace("\n", " ").strip()
    if role == "list":
        return re.sub(r"\n+", " ", text).strip()
    return re.sub(r"\n+", " ", text).strip()


def format_translated_blocks(blocks: list[TextBlock]) -> str:
    lines = []
    previous_role = None
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        role = block.role
        if role == "heading":
            if lines:
                lines.append("")
            lines.append(text)
            lines.append("")
        elif role == "subheading":
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(text)
        elif role == "greeting":
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(text)
        elif role == "list":
            if previous_role not in ("list", None) and lines and lines[-1] != "":
                lines.append("")
            lines.append("• " + text)
        else:
            if lines and lines[-1] != "" and previous_role not in ("greeting", "subheading"):
                lines.append("")
            lines.append(text)
        previous_role = role
    return "\n".join(lines).strip()


def block_marker(index: int) -> str:
    return f"§{index + 1}§"


def build_context_chunks(blocks: list[TextBlock], max_chars: int = 1800) -> tuple[list[str], list[TextBlock]]:
    chunks = []
    ordered_blocks = []
    current_lines = []
    current_len = 0
    for index, block in enumerate(blocks):
        marker = block_marker(index)
        line = f"{marker} {block.text}"
        if current_lines and current_len + len(line) > max_chars:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += len(line) + 1
        ordered_blocks.append(block)
    if current_lines:
        chunks.append("\n".join(current_lines))
    return chunks, ordered_blocks


def split_translated_marked_text(text: str, blocks: list[TextBlock]) -> list[TextBlock]:
    normalized = text
    for index in range(len(blocks)):
        marker = block_marker(index)
        normalized = re.sub(rf"\s*{re.escape(marker)}\s*", "\n" + marker + " ", normalized)

    found = {}
    current_index = None
    current_lines = []
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^§\s*(\d+)\s*§\s*(.*)$", line)
        if not match:
            match = re.match(r"^\[?\s*(\d+)\s*\]?[.)]\s+(.*)$", line)
        if match:
            if current_index is not None:
                found[current_index] = " ".join(current_lines).strip()
            current_index = int(match.group(1)) - 1
            current_lines = [match.group(2).strip()]
        elif current_index is not None:
            current_lines.append(line)
    if current_index is not None:
        found[current_index] = " ".join(current_lines).strip()

    translated_blocks = []
    if not found:
        return [TextBlock(polish_ukrainian_text(text), "paragraph")]
    for index, block in enumerate(blocks):
        translated = found.get(index, "").strip()
        if translated:
            translated_blocks.append(TextBlock(polish_translated_block(translated, block.role), block.role))
    return translated_blocks


class Translator:
    def __init__(self, settings: dict):
        self.settings = settings
        self.cache = {}
        self.cache_lock = threading.Lock()

    def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        cache_key = (self.settings.get("translate_engine", "google"), text)
        with self.cache_lock:
            cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        engine = self.settings.get("translate_engine", "google")
        if engine == "libretranslate":
            translated = self._libretranslate(text)
        else:
            translated = self._google(text)
        with self.cache_lock:
            if len(self.cache) > 600:
                self.cache.clear()
            self.cache[cache_key] = translated
        return translated

    def translate_many(self, chunks: list[str]) -> list[str]:
        if not chunks:
            return []
        results = [None] * len(chunks)
        pending = []
        for index, chunk in enumerate(chunks):
            cache_key = (self.settings.get("translate_engine", "google"), chunk)
            with self.cache_lock:
                cached = self.cache.get(cache_key)
            if cached is None:
                pending.append((index, chunk))
            else:
                results[index] = cached

        if pending:
            max_workers = min(4, len(pending))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(self.translate, chunk): (index, chunk)
                    for index, chunk in pending
                }
                for future in as_completed(future_map):
                    index, chunk = future_map[future]
                    try:
                        results[index] = future.result()
                    except Exception:
                        results[index] = self.translate(chunk)
        return [result or "" for result in results]

    def translate_readable(self, text: str) -> tuple[str, str]:
        blocks = clean_english_ocr_blocks(text)
        if not blocks:
            return "", ""
        context_chunks, ordered_blocks = build_context_chunks(blocks)
        translated_context = "\n".join(self.translate_many(context_chunks))
        formatted_blocks = split_translated_marked_text(translated_context, ordered_blocks)
        cleaned = "\n".join(block.text for block in blocks)
        translated = format_translated_blocks(formatted_blocks)
        return cleaned, translated

    def _google(self, text: str) -> str:
        url = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=en&tl=uk&dt=t&q={quote(text)}"
        )
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
        return "".join(part[0] for part in data[0] if part and part[0]).strip()

    def _libretranslate(self, text: str) -> str:
        base_url = self.settings.get("libretranslate_url", "").strip().rstrip("/")
        if not base_url:
            raise RuntimeError("У налаштуваннях не вказано LibreTranslate URL.")
        payload = {
            "q": text,
            "source": "en",
            "target": "uk",
            "format": "text",
        }
        key = self.settings.get("libretranslate_key", "").strip()
        if key:
            payload["api_key"] = key
        body = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{base_url}/translate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("translatedText", "").strip()


class OcrEngine:
    def __init__(self):
        self.tesseract = find_tesseract()

    def available(self) -> bool:
        return bool(self.tesseract)

    def recognize(self, image) -> str:
        if not self.tesseract:
            raise RuntimeError(
                "Tesseract OCR не знайдено. Встановіть Tesseract OCR і додайте його до PATH."
            )
        image = ImageOps.grayscale(image)
        image = ImageOps.autocontrast(image)
        image = ImageEnhance.Sharpness(image).enhance(1.4)
        pixels = image.width * image.height
        if pixels < 250_000:
            scale = 2.0
        elif pixels < 700_000:
            scale = 1.6
        else:
            scale = 1.25
        image = image.resize((int(image.width * scale), int(image.height * scale)))
        image = image.filter(ImageFilter.SHARPEN)
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "screen.png"
            out_base = Path(tmp) / "screen_text"
            image.save(in_path)
            cmd = [
                self.tesseract,
                str(in_path),
                str(out_base),
                "-l",
                "eng",
                "--oem",
                "1",
                "--psm",
                "6",
            ]
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
            return (out_base.with_suffix(".txt")).read_text(encoding="utf-8").strip()


class ResultWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.withdraw()
        self.title("Переклад")
        self.minsize(360, 140)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self.bind("<Escape>", lambda _event: self.withdraw())
        self.bind("<KeyPress>", self.on_key_press)
        self.bind("<Up>", lambda _event: self.app.translate_saved_region(-1))
        self.bind("<Down>", lambda _event: self.app.translate_saved_region(1))
        self._build()

    def _build(self):
        self.current_original = ""
        self.current_translated = ""
        self.is_popup_positioned = False
        self.is_region_overlay = False
        self.drag_start = None
        self.last_region = None

        self.container = tk.Frame(self, padx=18, pady=18)
        self.container.pack(fill="both", expand=True)

        self.handle = tk.Frame(self.container, height=3, cursor="fleur")
        self.handle.pack(fill="x", pady=(0, 10))
        self.handle.bind("<ButtonPress-1>", self.start_drag)
        self.handle.bind("<B1-Motion>", self.drag_window)

        self.translation_box = tk.Frame(self.container, highlightthickness=0, bd=0)
        self.translation_box.pack(fill="both", expand=True)
        self.translation_scroll = tk.Scrollbar(self.translation_box, bd=0, highlightthickness=0)
        self.translation_scroll.pack(side="right", fill="y")
        self.translation_text = tk.Text(
            self.translation_box,
            wrap="word",
            height=8,
            undo=False,
            borderwidth=0,
            highlightthickness=0,
            yscrollcommand=self.translation_scroll.set,
        )
        self.translation_text.pack(side="left", fill="both", expand=True)
        self.translation_scroll.configure(command=self.translation_text.yview)
        self.translation_text.bind("<Button-3>", self.show_context_menu)
        self.translation_text.bind("<Double-Button-1>", lambda _event: self.copy_translation())
        self.translation_text.bind("<Control-c>", lambda _event: self.copy_translation())
        self.translation_text.bind("<Escape>", lambda _event: self.withdraw())

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Копіювати переклад", command=self.copy_translation)
        self.menu.add_command(label="Показати/сховати оригінал", command=self.toggle_original)
        self.menu.add_command(label="Повторити", command=self.app.translate_last_region)
        self.menu.add_command(label="Нова область", command=self.app.select_region)
        self.menu.add_separator()
        self.menu.add_command(label="Налаштування", command=self.app.show_settings)
        self.menu.add_command(label="Закрити", command=self.withdraw)

        self.original_label = tk.Label(self.container, text="")
        original_box = tk.Frame(self.container, highlightthickness=0, bd=0)
        self.original_scroll = tk.Scrollbar(original_box, bd=0, highlightthickness=0)
        self.original_text = tk.Text(
            original_box,
            wrap="word",
            height=5,
            undo=False,
            borderwidth=0,
            highlightthickness=0,
            yscrollcommand=self.original_scroll.set,
        )
        self.original_text.pack(side="left", fill="both", expand=True)
        self.original_scroll.configure(command=self.original_text.yview)
        self.original_text.bind("<Escape>", lambda _event: self.withdraw())
        self.apply_theme()

    def apply_theme(self):
        theme = self.app.settings.get("theme", "light")
        size = int(self.app.settings.get("font_size", 15))
        if theme == "dark":
            bg, fg, panel, subpanel, muted = "#20242c", "#f4f7fb", "#20242c", "#171a20", "#7f8da3"
            accent = "#9fc5ff"
        else:
            bg, fg, panel, subpanel, muted = "#ffffff", "#07192c", "#ffffff", "#f7f8fa", "#d7dce2"
            accent = "#07192c"
        if self.is_region_overlay:
            size = 12
            bg, panel, subpanel, muted = "#ffffff", "#ffffff", "#ffffff", "#ffffff"
            fg = "#001b34"
            accent = fg
        self.configure(bg=bg)
        self.container.configure(bg=bg)
        self.handle.configure(bg=muted)
        self.translation_text.master.configure(bg=panel)
        self.original_text.master.configure(bg=subpanel)
        for text_widget, text_bg, text_size in (
            (self.translation_text, panel, size),
            (self.original_text, subpanel, max(10, size - 3)),
        ):
            text_widget.configure(
                bg=text_bg,
                fg=fg,
                insertbackground=fg,
                relief="flat",
                font=("Tahoma", text_size),
                padx=28 if self.is_region_overlay else 18,
                pady=12 if self.is_region_overlay else 14,
                spacing1=0,
                spacing2=2,
                spacing3=8 if self.is_region_overlay else 10,
                state="disabled",
            )
        self.translation_text.tag_configure(
            "heading",
            font=("Tahoma", max(size + 2, 14), "bold"),
            spacing1=0,
            spacing3=10 if self.is_region_overlay else 12,
        )
        self.translation_text.tag_configure(
            "subheading",
            font=("Tahoma", max(size, 12), "bold"),
            foreground=accent,
            lmargin1=0,
            lmargin2=0,
            spacing1=4,
            spacing3=8,
        )
        self.translation_text.tag_configure("paragraph", lmargin1=0, lmargin2=0, spacing3=8)
        self.translation_text.tag_configure("list", lmargin1=18, lmargin2=38, spacing3=6)

    def configure_result_mode(self, region=None):
        overlay = region is not None
        self.is_region_overlay = overlay
        if self.winfo_viewable():
            self.withdraw()
        try:
            self.overrideredirect(overlay)
        except Exception:
            pass
        if overlay:
            self.container.configure(padx=0, pady=0)
            self.handle.pack_forget()
            self.translation_scroll.pack_forget()
        else:
            self.container.configure(padx=18, pady=18)
            if not self.handle.winfo_ismapped():
                self.handle.pack(fill="x", pady=(0, 10), before=self.translation_box)
            if not self.translation_scroll.winfo_ismapped():
                self.translation_scroll.pack(side="right", fill="y")
        self.apply_theme()

    def set_text(self, widget, value: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if widget is self.translation_text:
            self.insert_formatted_translation(value.strip())
        else:
            widget.insert("end", value.strip())
        widget.configure(state="disabled")

    def insert_formatted_translation(self, value: str):
        lines = value.splitlines()
        first_content = True
        content_lines = [line.strip() for line in lines if line.strip()]
        content_index = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                self.translation_text.insert("end", "\n")
                continue
            next_line = content_lines[content_index + 1] if content_index + 1 < len(content_lines) else ""
            if stripped.startswith("• "):
                tag = "list"
            elif first_content and len(stripped) <= 90:
                tag = "heading"
            elif len(stripped) <= 80 and (
                next_line.startswith("• ") or not re.search(r"[.!?]$", stripped)
            ):
                tag = "subheading"
            else:
                tag = "paragraph"
            self.translation_text.insert("end", stripped + "\n", tag)
            first_content = False
            content_index += 1

    def start_drag(self, event):
        self.drag_start = (event.x_root, event.y_root, self.winfo_x(), self.winfo_y())

    def drag_window(self, event):
        if not self.drag_start:
            return
        start_x, start_y, window_x, window_y = self.drag_start
        self.geometry(f"+{window_x + event.x_root - start_x}+{window_y + event.y_root - start_y}")

    def toggle_original(self):
        if self.original_text.master.winfo_ismapped():
            self.original_text.master.pack_forget()
            return
        self.original_text.master.pack(fill="both", expand=False, pady=(6, 0))
        self.original_scroll.pack(side="right", fill="y")

    def copy_translation(self):
        self.copy_to_clipboard(self.current_translated)

    def copy_all(self):
        chunks = []
        if self.current_translated:
            chunks.append(self.current_translated)
        if self.current_original:
            chunks.append("OCR:\n" + self.current_original)
        self.copy_to_clipboard("\n\n".join(chunks))

    def copy_to_clipboard(self, value: str):
        value = value.strip()
        if not value:
            return
        self.clipboard_clear()
        self.clipboard_append(value)

    def show_context_menu(self, event=None):
        if event:
            self.menu.tk_popup(event.x_root, event.y_root)
        else:
            self.menu.tk_popup(self.winfo_rootx() + 10, self.winfo_rooty() + 10)

    def on_key_press(self, event):
        if event.char == "₴":
            self.show_context_menu()

    def show_text(self, title: str, original: str, translated: str, region=None):
        self.configure_result_mode(region)
        self.deiconify()
        self.is_popup_positioned = region is not None
        self.last_region = region
        self.geometry(self.popup_geometry(region))
        self.lift()
        self.attributes("-topmost", True)
        if not self.is_region_overlay:
            self.after(700, lambda: self.attributes("-topmost", False))
        self.after(10, self.focus_result_window)
        self.current_original = original.strip()
        self.current_translated = translated.strip()
        self.set_text(self.translation_text, self.current_translated)
        self.set_text(self.original_text, self.current_original)

        self.original_label.pack_forget()
        self.original_text.master.pack_forget()
        self.after(20, lambda region=region: self.fit_to_content(region))
        self.after(120, lambda region=region: self.fit_to_content(region))

    def focus_result_window(self):
        try:
            self.focus_force()
            self.translation_text.focus_set()
        except Exception:
            pass

    def popup_geometry(self, region=None) -> str:
        if region:
            return self.geometry_near_region(region)
        return self.normalized_geometry()

    def geometry_near_region(self, region) -> str:
        try:
            x1, y1, x2, y2 = [int(value) for value in region]
        except Exception:
            return self.normalized_geometry()

        width = max(20, x2 - x1)
        height = max(20, y2 - y1)
        return window_geometry(width, height, x1, y1)

    def fit_to_content(self, region=None):
        try:
            self.update_idletasks()
            current = self.geometry()
            size, position = current.split("+", 1)
            width, _height = [int(part) for part in size.split("x", 1)]
            pos_x, pos_y = [int(part) for part in position.split("+", 1)]
            screen_height = self.winfo_screenheight()

            char_px = 7 if self.is_region_overlay else 8
            horizontal_padding = 60 if self.is_region_overlay else 52
            self.translation_text.configure(width=max(24, (width - horizontal_padding) // char_px))
            self.update_idletasks()
            last_index = self.translation_text.index("end-1c")
            bbox = self.translation_text.bbox(last_index)
            if bbox:
                content_bottom = bbox[1] + bbox[3]
            else:
                content_bottom = self.translation_text.winfo_reqheight()
            if self.is_region_overlay and region:
                return
            wanted = min(max(190, content_bottom + 72), 660, screen_height - 80)
            if region:
                _x1, y1, _x2, _y2 = [int(value) for value in region]
                y = max(10, min(screen_height - wanted - 40, y1))
                self.geometry(f"{width}x{wanted}+{pos_x}+{y}")
            else:
                self.geometry(f"{width}x{wanted}+{pos_x}+{pos_y}")
        except Exception:
            pass

    def normalized_geometry(self) -> str:
        geometry = self.app.settings.get("window_geometry", "660x470+80+80")
        try:
            size, position = geometry.split("+", 1)
            width, height = [int(part) for part in size.split("x", 1)]
            if width < 620 or height < 420:
                return f"660x470+{position}"
        except Exception:
            return "660x470+80+80"
        return geometry


class RegionSelector(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.start_x = self.start_y = 0
        self.rect = None
        self.screenshot = ImageGrab.grab(all_screens=True)
        self.photo = ImageTk.PhotoImage(self.screenshot)
        self.screen_x, self.screen_y, _screen_width, _screen_height = virtual_screen_rect()

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.92)
        width, height = self.screenshot.size
        self.geometry(window_geometry(width, height, self.screen_x, self.screen_y))

        self.canvas = tk.Canvas(self, cursor="cross", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.create_rectangle(0, 0, width, height, fill="#111827", stipple="gray50")
        self.tip = self.canvas.create_text(
            width // 2,
            32,
            text="Виділіть англійський текст. Esc - скасувати.",
            fill="white",
            font=("Segoe UI", 16, "bold"),
        )

        self.bind("<Escape>", lambda _event: self.destroy())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        self.rect = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            self.start_x,
            self.start_y,
            outline="#00d084",
            width=3,
        )

    def on_drag(self, event):
        if self.rect:
            self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        x1, y1 = min(self.start_x, event.x), min(self.start_y, event.y)
        x2, y2 = max(self.start_x, event.x), max(self.start_y, event.y)
        self.destroy()
        if x2 - x1 < 10 or y2 - y1 < 10:
            return
        self.app.translate_region(
            (
                x1 + self.screen_x,
                y1 + self.screen_y,
                x2 + self.screen_x,
                y2 + self.screen_y,
            )
        )


class SettingsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Налаштування")
        self.resizable(False, False)
        self._build()

    def _build(self):
        frame = tk.Frame(self, padx=16, pady=14)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Розмір шрифту").grid(row=0, column=0, sticky="w")
        self.font_size = tk.IntVar(value=int(self.app.settings.get("font_size", 15)))
        tk.Spinbox(frame, from_=10, to=28, textvariable=self.font_size, width=6).grid(
            row=0, column=1, sticky="w", padx=(12, 0)
        )

        tk.Label(frame, text="Тема").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.theme = tk.StringVar(value=self.app.settings.get("theme", "light"))
        tk.OptionMenu(frame, self.theme, "light", "dark").grid(
            row=1, column=1, sticky="w", padx=(12, 0), pady=(10, 0)
        )

        tk.Label(frame, text="Перекладач").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.engine = tk.StringVar(value=self.app.settings.get("translate_engine", "google"))
        tk.OptionMenu(frame, self.engine, "google", "libretranslate").grid(
            row=2, column=1, sticky="w", padx=(12, 0), pady=(10, 0)
        )

        tk.Label(frame, text="Стиль тексту").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.style_mode = tk.StringVar(value=self.app.settings.get("style_mode", "readable"))
        tk.OptionMenu(frame, self.style_mode, "readable", "plain").grid(
            row=3, column=1, sticky="w", padx=(12, 0), pady=(10, 0)
        )

        tk.Label(frame, text="LibreTranslate URL").grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.lt_url = tk.Entry(frame, width=36)
        self.lt_url.insert(0, self.app.settings.get("libretranslate_url", ""))
        self.lt_url.grid(row=4, column=1, sticky="w", padx=(12, 0), pady=(10, 0))

        tk.Label(frame, text="LibreTranslate key").grid(row=5, column=0, sticky="w", pady=(10, 0))
        self.lt_key = tk.Entry(frame, width=36, show="*")
        self.lt_key.insert(0, self.app.settings.get("libretranslate_key", ""))
        self.lt_key.grid(row=5, column=1, sticky="w", padx=(12, 0), pady=(10, 0))

        buttons = tk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(16, 0))
        tk.Button(buttons, text="Зберегти", command=self.save).pack(side="right")
        tk.Button(buttons, text="Скасувати", command=self.destroy).pack(side="right", padx=(0, 8))

    def save(self):
        self.app.settings["font_size"] = int(self.font_size.get())
        self.app.settings["theme"] = self.theme.get()
        self.app.settings["translate_engine"] = self.engine.get()
        self.app.settings["style_mode"] = self.style_mode.get()
        self.app.settings["libretranslate_url"] = self.lt_url.get().strip()
        self.app.settings["libretranslate_key"] = self.lt_key.get().strip()
        save_settings(self.app.settings)
        self.app.result_window.apply_theme()
        self.destroy()


class ScreenTranslatorApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.withdraw()
        self.settings = load_settings()
        self.events = queue.Queue()
        self.ocr = OcrEngine()
        self.translator = Translator(self.settings)
        self.result_window = ResultWindow(self)
        self.hotkey_thread = None
        self.hotkey_thread_id = None
        self.stop_hotkey = threading.Event()
        self.last_regions = [tuple(region) for region in self.settings.get("last_regions", [])]
        self.active_region_index = 0
        self.last_hotkey_time = 0.0

        self.root.after(100, self.process_events)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.start_hotkey_listener()
        self.show_startup()

    def show_startup(self):
        self.result_window.show_text(
            "Готово: Ctrl+Alt+T - виділити область",
            "",
            "Натисніть Ctrl+Alt+T і обведіть англійський текст на екрані.\n\n"
            "Після перекладу з'явиться тільки текст у маленькому popup-вікні. "
            "Подвійне Ctrl+Alt+T повторює останню область. "
            "Колесо або Up/Down у popup перемикає збережені області.",
        )
        if not self.ocr.available():
            self.result_window.show_text(
                "OCR ще не підключено",
                "",
                "Встановіть Tesseract OCR з англійською мовою eng, потім запустіть програму ще раз.",
            )

    def start_hotkey_listener(self):
        self.hotkey_thread = threading.Thread(target=self.hotkey_loop, daemon=True)
        self.hotkey_thread.start()

    def hotkey_loop(self):
        user32 = ctypes.windll.user32
        self.hotkey_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, VK_T):
            self.events.put(("error", "Не вдалося зареєструвати Ctrl+Alt+T."))
            return
        msg = ctypes.wintypes.MSG()
        while not self.stop_hotkey.is_set():
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0:
                break
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                now = time.time()
                if now - self.last_hotkey_time < 0.45:
                    self.events.put(("repeat", None))
                    self.last_hotkey_time = 0.0
                else:
                    self.events.put(("select", None))
                    self.last_hotkey_time = now
        user32.UnregisterHotKey(None, HOTKEY_ID)

    def process_events(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "select":
                    self.select_region()
                elif event == "repeat":
                    self.translate_last_region()
                elif event == "error":
                    messagebox.showerror(APP_NAME, payload)
        except queue.Empty:
            pass
        self.root.after(100, self.process_events)

    def select_region(self):
        RegionSelector(self)

    def translate_last_region(self):
        if not self.last_regions:
            self.result_window.show_text("Немає збереженої області", "", "Спочатку виділіть текст.")
            return
        self.active_region_index = 0
        self.translate_region(self.last_regions[0])

    def translate_saved_region(self, step: int):
        if not self.last_regions:
            return
        self.active_region_index = (self.active_region_index + step) % len(self.last_regions)
        self.translate_region(self.last_regions[self.active_region_index], remember=False)

    def translate_region(self, region, remember=True):
        if remember:
            self.remember_region(region)
        self.result_window.show_text("Розпізнаю текст...", "", "", region=region)
        threading.Thread(target=self._translate_worker, args=(region,), daemon=True).start()

    def remember_region(self, region):
        region = tuple(int(v) for v in region)
        self.last_regions = [r for r in self.last_regions if r != region]
        self.last_regions.insert(0, region)
        self.active_region_index = 0
        self.last_regions = self.last_regions[:8]
        self.settings["last_regions"] = [list(r) for r in self.last_regions]
        save_settings(self.settings)

    def _translate_worker(self, region):
        try:
            image = ImageGrab.grab(bbox=region, all_screens=True)
            original = self.ocr.recognize(image)
            if not original:
                translated = "Не вдалося розпізнати текст у цій області."
                displayed_original = ""
            elif self.settings.get("style_mode", "readable") == "readable":
                displayed_original, translated = self.translator.translate_readable(original)
            else:
                translated = self.translator.translate(original)
                displayed_original = original
            self.root.after(
                0,
                lambda displayed_original=displayed_original, translated=translated, region=region: self.result_window.show_text(
                    "Переклад з англійської українською", displayed_original, translated, region=region
                ),
            )
        except Exception as exc:
            error_text = str(exc)
            self.root.after(
                0,
                lambda error_text=error_text: self.result_window.show_text(
                    "Помилка", "", error_text
                ),
            )

    def show_settings(self):
        SettingsWindow(self)

    def quit(self):
        if not self.result_window.is_popup_positioned:
            self.settings["window_geometry"] = self.result_window.geometry()
        save_settings(self.settings)
        self.stop_hotkey.set()
        if self.hotkey_thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.hotkey_thread_id, 0x0012, 0, 0)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if sys.platform != "win32":
        print("This utility is designed for Windows.")
        sys.exit(1)
    ScreenTranslatorApp().run()
