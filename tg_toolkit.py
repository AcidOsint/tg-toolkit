# tg_toolkit.py
"""
tg_toolkit v6.8.1 — OSINT-профайлинг Telegram HTML/TXT экспортов.
Один файл, только стандартная библиотека, Python 3.9+.
Структурный парсинг, форварды с атрибуцией, реакции, профиль чата,
валидация сущностей, per-run папки, атомарная запись.
"""

import io
import re
import csv
import json
import os
import sys
import hashlib
import subprocess
import statistics
import unicodedata
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict
from html.parser import HTMLParser

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

MAX_FILE_SIZE = 200 * 1024 * 1024        # 200 МБ на файл
MAX_TOTAL_MERGE_SIZE = 1024 ** 3         # 1 ГБ суммарно для merge
MAX_FILES = 10_000                       # файлов за проход
MAX_SCAN_ENTRIES = 100_000               # записей дерева при сканировании
MAX_SEARCH_RESULTS = 10_000              # строк в файле поиска
HEADER_ZONE = 12                         # непустых строк шапки на источник

RED = "\033[91m"
DIM = "\033[90m"
RESET = "\033[0m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
BOLD = "\033[1m"

# Только стоп-слова статистики топ-слов (тело сообщений не фильтруют).
NOISE_WORDS = set([
    "reply", "sticker", "photo", "video", "file", "voice", "audio", "gif",
    "edited", "forwarded", "media", "document", "attachment", "joined",
    "left", "pinned", "message", "messages", "html", "export", "channel",
    "data", "included", "change", "exporting", "settings", "download",
    "animation", "content", "background", "history", "page", "chat",
    "json", "replying", "available", "telegram", "messenger", "theme",
    "attach", "proxy", "cache", "general", "privacy", "security", "device",
    "devices", "folder", "folders", "shared", "link", "links", "open",
    "close", "save", "saved", "loading", "default", "advanced", "profile",
    "desktop", "mobile", "version", "archive", "include", "includes",
    "exported", "downloaded", "setting", "animated", "emoji", "stickers",
    "forward", "forwards", "views", "view", "online", "offline"
])
RU_UA_STOP = set(["это", "если", "только", "когда", "потом", "также",
    "который", "очень", "было", "меня", "тебя", "него", "этого", "после",
    "просто", "можно", "нужно", "надо", "чтобы", "этот"])
EN_STOP = set(["this", "that", "with", "from", "have", "were", "been",
    "they", "them", "their", "about", "there", "would", "could", "should",
    "after", "before", "where", "which"])
STATS_STOP = NOISE_WORDS | RU_UA_STOP | EN_STOP

REGEX_PATTERNS = {
    "tags": r"(?<![\w./:])@([A-Za-z0-9_]{3,})",
    "tme_links": r"(?i)https?://(?:t\.me|telegram\.me)(?:/[A-Za-z0-9_+/\-?=&#.%~:]*)?(?!\w|\.\w)",
    "urls": r'(?i)https?://(?!(?:t\.me|telegram\.me)(?:[/?#]|$))[^\s)>\]"]+',
    "emails": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "phones": r"(?:\+?\d[\d\-\(\) ]{8,}\d)",
    "cards": r"\b(?:\d{4}[ -]?){3}\d{4}\b",
    "crypto_btc": r"\b(?:bc1[0-9a-z]{38,61}|[13][a-zA-HJ-NP-Z0-9]{25,39})\b",
    "crypto_eth_bsc": r"\b0x[a-fA-F0-9]{40}\b",
    "crypto_trx": r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b",
    "ipv4": r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b",
    "fio_ru": r"\b[А-ЯЁІЇЄҐ][а-яёіїєґ\-]+\s+[А-ЯЁІЇЄҐ][а-яёіїєґ\-]+\s+[А-ЯЁІЇЄҐ][а-яёіїєґ\-]+\b",
}
COMPILED_PATTERNS = {k: re.compile(v) for k, v in REGEX_PATTERNS.items()}
LINK_RSTRIP = ":.,);'\"[]"

STRUCT_PREFIX_RE = re.compile(
    r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?(?: UTC[+-]\d{2}:\d{2})?\] ")
MSG_PREFIX_LINE_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
DATE_SHAPED_RE = re.compile(
    r"(?:\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})(?:\s\d{1,2})?"
    r"|\d{1,2}\s(?:\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})")
HEADER_RX = [re.compile(p) for p in (
    r"^exported (?:from|with) telegram",
    r"^экспорт\w* из telegram",
    r"^version [\d.]+",
    r"^версия [\d.]+",
    r"^\d+ (?:members|messages|subscribers|участник\w*|подписчик\w*|сообщени\w*)(?:[ ,].*)?$",
    r"^page \d+(?: of \d+)?$",
    r"^страница \d+(?: из \d+)?$",
    r"^channel: ",
    r"^канал: ",
    r"^chat history",
    r"^история (?:чата|переписки)",
    r"^shared media",
    r"^общие медиа",
    r"^message$",
    r"^data$",
)]
ALWAYS_SKIP_RX = [re.compile(p) for p in (
    r"^not included, change data exporting settings",
    r"^не включено, измените настройки экспорта",
    r"^не включено, змініть налаштування експорту",
    r"^(?![a-zа-яёіїєґ0-9])[^,]{1,12}, [\d.]+\s*[kmgt]b$",
    r"^\d{1,2}:\d{2}, [\d.]+\s*[kmgt]b$",
    r"^[\d.]+\s*[kmgt]b$",
    r"^\d+\s*[×x]\s*\d+(?:,\s.*)?$",
)]
MEDIA_LINE_RE = re.compile(
    r"(?:video\s+message|voice\s+message|video\s+file"
    r"|видео\s+сообщение|голосовое\s+сообщение|видеофайл|видеосообщение"
    r"|пересланное\s+сообщение"
    r"|photo|video|audio|voice|gif|sticker|file|edited|forwarded|reply|media|document|animation"
    r"|фото|видео|аудио|голосовое|файл|стикер|анимация|медиа|документ|изменено|ответ):?\s*\d*")
KEYVAL_RE = re.compile(r"[a-zа-яё_]+:\s*\d+")
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁёІіЇїЄє0-9_\-]{4,}")
TME_USER_RE = re.compile(r"(?i)^https?://(?:t\.me|telegram\.me)(?:/s)?/([A-Za-z0-9_]+)(?:[/?#].*)?$")
TME_RESERVED = {"s", "c", "joinchat", "addstickers", "share", "proxy",
                "boost", "giftcode", "setlanguage", "bg", "socks", "iv", "login"}
FWD_DATE_IN_NAME_RE = re.compile(
    r"\s*\d{2}\.\d{2}\.\d{4}[ T]\d{2}:\d{2}(?::\d{2})?(?:\s*UTC[+-]\d{2}:\d{2})?\s*$")
USERPIC_TOKEN_RE = re.compile(r"userpic(?:_wrap|\d+)?")

MSG_LINE_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?)(?: UTC([+-])(\d{2}):(\d{2}))?\] (.+)$")
FWD_NOTE_SPLIT_RE = re.compile(r"^(.*?)\s*\[переслано от ([^\]]+)\]$")
REACT_LINE_RE = re.compile(r"^\[реакции: (.+)\]$")
DATE_WORD_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# ==========================================
# УТИЛИТЫ
# ==========================================
def csv_safe(v):
    v = str(v)
    return "'" + v if v.startswith(("=", "+", "-", "@")) else v

def natural_key(path: Path, root: Path):
    rel = path.relative_to(root)
    key = [(0, p.lower()) for p in rel.parts[:-1]]
    key += [(1, int(s)) if s.isdigit() else (0, s.lower())
            for s in re.split(r"(\d+)", rel.stem)]
    key.append((0, rel.suffix.lower()))
    return key

def parse_date_title(title):
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})[ T](\d{2}):(\d{2})(?::(\d{2}))?\s*(UTC[+-]\d{2}:\d{2})?",
                  title or "")
    if not m:
        return ""
    out = f"{m.group(3)}-{m.group(2)}-{m.group(1)} {m.group(4)}:{m.group(5)}"
    if m.group(6):
        out += f":{m.group(6)}"
    if m.group(7):
        out += f" {m.group(7)}"
    return out

def _is_glue(ch):
    return bool(unicodedata.combining(ch)) or ch == "\u200d"

def _is_detachable(ch):
    return ch == "\ufe0f" or 0x1F3FB <= ord(ch) <= 0x1F3FF

def _is_regional(ch):
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF

def safe_truncate(line, limit=120):
    if len(line) <= limit:
        return line
    cut = line[:limit]
    while cut and cut[-1] == "\u200d":
        cut = cut[:-1]
        while cut and (_is_glue(cut[-1]) or _is_detachable(cut[-1])):
            cut = cut[:-1]
    while cut and len(line) > len(cut) and _is_glue(line[len(cut)]):
        cut = cut[:-1]
        while cut and (_is_glue(cut[-1]) or _is_detachable(cut[-1])):
            cut = cut[:-1]
    n = 0
    i = len(cut) - 1
    while i >= 0 and _is_regional(cut[i]):
        n += 1
        i -= 1
    if n % 2 == 1:
        cut = cut[:-1]
    return cut + "..."

def luhn_ok(number):
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 12:
        return False
    checksum, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

def btc_base58check_ok(addr: str) -> bool:
    if not 26 <= len(addr) <= 35 or addr[0] not in "13":
        return False
    num = 0
    for ch in addr:
        if ch not in B58_ALPHABET:
            return False
        num = num * 58 + B58_ALPHABET.index(ch)
    try:
        raw = num.to_bytes(25, "big")
    except OverflowError:
        return False
    return hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:]

def _bech32_polymod(values):
    gen = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= gen[i]
    return chk

def btc_bech32_ok(addr: str) -> bool:
    if not addr.lower().startswith("bc1") or not 14 <= len(addr) <= 90:
        return False
    a = addr.lower()
    if a != addr and addr != addr.upper():
        return False
    pos = a.rfind("1")
    if pos < 1 or pos + 7 > len(a):
        return False
    try:
        data = [_BECH32_CHARSET.index(c) for c in a[pos + 1:]]
    except ValueError:
        return False
    if not data:
        return False
    hrp = a[:pos]
    expanded = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    const = 1 if data[0] == 0 else 0x2bc830a3
    return _bech32_polymod(expanded + data) == const

def normalize_phone_key(raw):
    digits = re.sub(r"\D", "", raw)
    if not (10 <= len(digits) <= 15) or len(set(digits)) <= 2:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits

def is_safe_input_file(path: Path, root: Path) -> bool:
    try:
        if path.is_symlink():
            return False
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False

def safe_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\x00-\x1f\x7f]", "_", name)
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name.strip(" ._") or "file"

def get_unique_out_name(file: Path, used_names: set) -> str:
    parts = [safe_name(p) for p in file.relative_to(INPUT_DIR).with_suffix("").parts]
    base = "_".join(parts) + "_" + safe_name(file.suffix.lower().lstrip("."))
    out, n = base, 2
    while out in used_names:
        out = f"{base}__{n}"
        n += 1
    used_names.add(out)
    return out

def read_text_smart(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError(f"файл больше {MAX_FILE_SIZE // (1024 * 1024)} МБ")
    except OSError as e:
        raise ValueError(f"нет доступа: {e}")
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return unicodedata.normalize("NFKC", raw.decode("utf-16", errors="replace"))
    if b"\x00" in raw[:4096]:
        raise ValueError("похоже на бинарный файл (NUL-байты)")
    try:
        return unicodedata.normalize("NFKC", raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        pass
    m = re.search(rb'charset\s*=\s*["\']?([\w\-]+)', raw[:2048], re.I)
    if m:
        enc = m.group(1).decode("ascii", "ignore").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                text = raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                text = None
            if text is not None:
                print(YELLOW + f"[!] {path.name}: прочитано как {enc} (charset из meta)" + RESET)
                return unicodedata.normalize("NFKC", text)
    try:
        text = raw.decode("cp1251")
        print(YELLOW + f"[!] {path.name}: не UTF-8, прочитано как cp1251 — проверьте кириллицу" + RESET)
        return unicodedata.normalize("NFKC", text)
    except UnicodeDecodeError:
        pass
    print(YELLOW + f"[!] {path.name}: жёсткая замена битых символов" + RESET)
    return unicodedata.normalize("NFKC", raw.decode("utf-8", errors="replace"))

def atomic_write(path: Path, text: str):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if os.name != "nt":
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    os.replace(tmp, path)

def new_run_dir(kind: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = OUTPUT_DIR / f"{kind}_{stamp}"
    n = 2
    while run_dir.exists():
        run_dir = OUTPUT_DIR / f"{kind}_{stamp}__{n}"
        n += 1
    run_dir.mkdir(parents=True)
    if os.name != "nt":
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass
    return run_dir

# ==========================================
# HTML-ПАРСЕР
# ==========================================
class TgParser(HTMLParser):
    BLOCK = {"p", "li", "tr", "table", "blockquote",
             "h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.pending_date = ""
        self.pending_author = ""
        self.last_author = ""
        self.text_emitted = True
        self.reuse_author = False
        self.media_seen = False
        self.author_mode = False
        self.author_buf = []
        self.suppress_depth = 0
        self.link_href = None
        self.link_buf = []
        self.trim_next = False
        self.in_forwarded = False
        self.fwd_author = ""
        self.fwd_date = ""
        self.had_forward = False
        self.last_fwd_note = ""
        self.in_reactions = False
        self.react_emoji_open = False
        self.cur_emoji = ""
        self.cur_reactors = []
        self.message_reactions = []

    def _in_skip(self):
        return any(s.get("skip") for s in self.stack)

    def _header_prefix(self):
        author = self.pending_author
        if not author and self.reuse_author:
            author = self.last_author
        prefix = f"[{self.pending_date}] " if self.pending_date else ""
        note = ""
        if self.had_forward:
            if self.fwd_author:
                note = f" [переслано от {self.fwd_author}"
                if self.fwd_date:
                    note += f", {self.fwd_date[:16]}"
                note += "]"
                self.last_fwd_note = note
            else:
                note = self.last_fwd_note
        if author:
            prefix += f"{author}{note}: "
            self.last_author = author
        elif note:
            prefix += f"{note.strip()}: "
        return prefix

    def _flush_header(self):
        self.out.append("\n" + self._header_prefix())
        self.text_emitted = True
        self.trim_next = True
        self.pending_date = ""
        self.pending_author = ""

    def _close_message(self):
        if not self.text_emitted and self.media_seen and (self.pending_date or self.pending_author):
            self.out.append("\n" + self._header_prefix() + "[медиа]")
        if self.message_reactions:
            parts = [f"{emoji} — {'; '.join(reactors)}"
                     for emoji, reactors in self.message_reactions]
            self.out.append("\n [реакции: " + ", ".join(parts) + "]")
        self.pending_date = ""
        self.pending_author = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        info = {"tag": tag, "cls": cls}

        if tag in self.SKIP or self._in_skip():
            info["skip"] = True
            self.stack.append(info)
            return
        if self.suppress_depth:
            info["ignored"] = True
            if self.in_reactions:
                if tag == "span" and "emoji" in cls:
                    info["react_emoji"] = True
                    self.react_emoji_open = True
                elif tag == "div" and a.get("title"):
                    self.cur_reactors.append(a["title"].strip())
            self.stack.append(info)
            return

        if tag == "span" and (cls & {"date", "reactions"}):
            if "reactions" in cls:
                self.in_reactions = True
                self.cur_emoji = ""
                self.cur_reactors = []
                info["reactions_span"] = True
            elif self.in_forwarded and "date" in cls:
                d = parse_date_title(a.get("title") or "")
                if d:
                    self.fwd_date = d
            info["sup"] = True
            self.suppress_depth += 1
            self.stack.append(info)
            return

        if tag == "div":
            if "date" in cls or "reply_to" in cls:
                d = parse_date_title(a.get("title") or "")
                if d:
                    self.pending_date = d
                info["sup"] = True
                self.suppress_depth += 1
            elif "from_name" in cls:
                self.author_mode = True
                self.author_buf = []
                info["from_name"] = True
                if self.in_forwarded:
                    info["fwd_name"] = True
            elif "text" in cls:
                self._flush_header()
                info["text_div"] = True
            elif "message" in cls:
                if "service" in cls:
                    info["sup"] = True
                    self.suppress_depth += 1
                else:
                    self.text_emitted = False
                    self.media_seen = False
                    self.reuse_author = "joined" in cls
                    self.pending_date = ""
                    self.pending_author = ""
                    self.fwd_author = ""
                    self.fwd_date = ""
                    self.had_forward = False
                    self.message_reactions = []
                info["message_div"] = True
            elif "media_wrap" in cls:
                self.media_seen = True
            elif any(USERPIC_TOKEN_RE.fullmatch(c) for c in cls):
                info["sup"] = True
                self.suppress_depth += 1
            elif "forwarded" in cls:
                self.in_forwarded = True
                self.had_forward = True
                info["fwd_div"] = True
            else:
                self.out.append("\n")
        elif tag == "br":
            self.out.append("\n")
        elif tag == "img":
            if cls & {"photo", "sticker", "video", "gif", "animated"}:
                self.media_seen = True
            alt = a.get("alt")
            if alt:
                self.out.append(f" {alt} ")
        elif tag == "a":
            href = a.get("href") or ""
            if href.startswith(("http://", "https://", "tg://", "mailto:")):
                self.link_href = href
                self.link_buf = []
                info["link"] = True
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in self.BLOCK:
            self.out.append("\n")

        self.stack.append(info)

    def handle_endtag(self, tag):
        tag = tag.lower()
        info = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                info = self.stack.pop(i)
                break
        if info is None:
            return
        if info.get("skip") or info.get("ignored"):
            if info.get("react_emoji"):
                self.react_emoji_open = False
            return
        if info.get("sup"):
            self.suppress_depth = max(0, self.suppress_depth - 1)
            if info.get("reactions_span"):
                self.in_reactions = False
                emoji = self.cur_emoji.strip()
                if emoji and self.cur_reactors:
                    self.message_reactions.append(
                        (emoji, list(dict.fromkeys(self.cur_reactors))))
            return
        if info.get("fwd_div"):
            self.in_forwarded = False
            return
        if info.get("from_name"):
            raw_author = re.sub(r"\s+", " ", "".join(self.author_buf)).strip()
            author = FWD_DATE_IN_NAME_RE.sub("", raw_author).strip()
            if info.get("fwd_name"):
                self.fwd_author = author
            else:
                self.pending_author = author
            self.author_mode = False
            return
        if info.get("link"):
            text = "".join(self.link_buf).strip()
            href = self.link_href
            bare = re.sub(r"^https?://", "", href)
            if not text:
                self.out.append(f" [{href}] ")
            elif text in (href, bare):
                self.out.append(f" {text} ")
            else:
                self.out.append(f" {text} [{href}] ")
            self.link_href = None
            return
        if info.get("message_div"):
            self._close_message()
            return
        if info.get("text_div"):
            self.trim_next = False
            if self.media_seen:
                self.out.append(" [медиа]")
            return
        if tag == "td":
            self.out.append(" | ")
            return
        if tag in self.BLOCK or tag == "div":
            self.out.append("\n")

    def handle_data(self, data):
        if self.react_emoji_open:
            self.cur_emoji += data
            return
        if self.suppress_depth or self._in_skip():
            return
        if self.author_mode:
            self.author_buf.append(data)
        elif self.link_href is not None:
            self.link_buf.append(data)
        else:
            if self.trim_next:
                stripped = data.lstrip(" \t\r\n")
                if not stripped:
                    return
                data = stripped
                self.trim_next = False
            self.out.append(data)

    def close(self):
        super().close()
        if self.link_href:
            self.out.append(f" [{self.link_href}] ")
            self.link_href = None

def html_to_text(html_path: Path) -> str:
    parser = TgParser()
    parser.feed(read_text_smart(html_path))
    parser.close()
    text = "".join(parser.out)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

# ==========================================
# ИНТЕРФЕЙС
# ==========================================
def init_folders():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        for d in (INPUT_DIR, OUTPUT_DIR):
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass

def clear_screen():
    if os.name == "nt":
        os.system("")
    print("\033[2J\033[H", end="")

def print_header():
    logo = [
        r"   ██████╗  ██╗",
        r"  ██╔═══██╗████║",
        r"  ██║   ██║╚═██║",
        r"  ██║▄▄ ██║  ██║",
        r"  ╚██████╔╝  ██║",
        r"   ╚══▀▀═╝   ╚═╝"
    ]
    print("")
    for line in logo:
        print(RED + BOLD + line + RESET)
    print("")
    print(DIM + "AUTHOR AcidOsint | BUILD public | VERSION 6.8.1 | UNIT Q1 TOOLS" + RESET)
    print(DIM + "=" * 78 + RESET)
    print("")

def print_menu():
    print_header()
    for item in (
        "01 * HTML -> ОЧИСТКА + СУЩНОСТИ + ПРОФИЛЬ (TXT/CSV/JSON)",
        "02 * TXT -> ОЧИСТКА + СУЩНОСТИ + ПРОФИЛЬ (готовые txt-дампы)",
        "03 * ПОЛНЫЙ ПАЙПЛАЙН (HTML, затем TXT)",
        "04 * ПОИСК (подстрока / целые слова / regex + контекст)",
        "05 * ОТКРЫТЬ РАБОЧИЕ ПАПКИ",
        "06 * ВЫХОД",
    ):
        print(RED + f"  {item}" + RESET)
    print(DIM + "  * 01 и 02 сразу дают очищенный *_clean.txt + отчеты: повторно чистить не нужно" + RESET)
    print(DIM + "  * каждый прогон сохраняется в свою подпапку output/, ничего не перезаписывается" + RESET)
    print("")

# ==========================================
# ФАЙЛЫ И ОЧИСТКА
# ==========================================
def get_files(extensions, folder=INPUT_DIR):
    if not folder.exists():
        return []
    safe, dropped, scanned = [], 0, 0
    try:
        for f in folder.rglob("*"):
            scanned += 1
            if scanned > MAX_SCAN_ENTRIES:
                print(YELLOW + f"[!] Дерево {folder.name} слишком большое: "
                               f"просканировано {MAX_SCAN_ENTRIES} записей, остальное пропущено" + RESET)
                break
            try:
                if not f.is_file() or f.suffix.lower() not in extensions:
                    continue
                if not is_safe_input_file(f, folder):
                    dropped += 1
                    continue
                safe.append(f)
            except OSError:
                continue
    except OSError:
        pass
    if dropped:
        print(YELLOW + f"[!] Пропущено небезопасных путей (симлинки): {dropped}" + RESET)
    files = sorted(safe, key=lambda p: natural_key(p, folder))
    if len(files) > MAX_FILES:
        print(YELLOW + f"[!] Файлов больше {MAX_FILES} — обработаны первые {MAX_FILES}" + RESET)
        files = files[:MAX_FILES]
    return files

def clean_text_content(text):
    lines = text.splitlines()
    original_count = len(lines)
    marker_idx = [i for i, l in enumerate(lines)
                  if l.startswith("### SOURCE:") and l.endswith("###")]
    bounds = [0] + [i + 1 for i in marker_idx] + [len(lines)]
    struct_flags = [any(MSG_PREFIX_LINE_RE.match(l)
                        for l in lines[bounds[b]:bounds[b + 1]])
                    for b in range(len(bounds) - 1)]
    cleaned = []
    pos = 0
    in_message = False
    block = 0
    for raw_line in lines:
        if raw_line.startswith("### SOURCE:") and raw_line.endswith("###"):
            pos = 0
            in_message = False
            block = min(block + 1, len(struct_flags) - 1)
            cleaned.append(raw_line)
            continue
        line = re.sub(r"\s+", " ", raw_line.replace("\xa0", " ")).strip()
        if not line:
            continue
        pos += 1
        low = line.lower()
        is_noise = False
        if pos <= HEADER_ZONE:
            for rx in HEADER_RX:
                if rx.search(low):
                    is_noise = True
                    break
        if not is_noise:
            for rx in ALWAYS_SKIP_RX:
                if rx.search(low):
                    is_noise = True
                    break
        if not is_noise and len(low.split()) <= 3:
            if MEDIA_LINE_RE.fullmatch(low) or KEYVAL_RE.fullmatch(low):
                is_noise = True
        if is_noise:
            continue
        if struct_flags[block]:
            if MSG_PREFIX_LINE_RE.match(line):
                in_message = True
            elif len(line) <= 2 and not in_message:
                continue
        cleaned.append(line)
    final_count = len(cleaned)
    percent = round((1 - final_count / original_count) * 100, 1) if original_count else 0
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()
    return out, original_count, final_count, percent

# ==========================================
# СУЩНОСТИ
# ==========================================
def _derive_accounts(entities):
    tags = entities.get("tags") or {}
    links = entities.get("tme_links") or {}
    if not tags or not links:
        return
    link_users = {}
    for link in links:
        m = TME_USER_RE.match(link)
        if m and m.group(1).lower() not in TME_RESERVED:
            link_users[m.group(1).lower()] = link
    if not link_users:
        return
    accounts = {}
    for tag_val, ctxs in tags.items():
        nick = tag_val.lstrip("@").lower()
        if nick in link_users:
            key = f"@{nick} + {link_users[nick]}"
            merged = list(dict.fromkeys(
                accounts.get(key, []) + ctxs + links[link_users[nick]]))
            accounts[key] = merged[:3]
    if accounts:
        entities["accounts"] = accounts

def extract_entities_with_context(text):
    entities = defaultdict(lambda: defaultdict(list))
    current_file_ctx = ""
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if line.startswith("### SOURCE:") and line.endswith("###"):
            current_file_ctx = f"[{line.strip('# ').replace('SOURCE: ', '')}] "
            continue
        context_str = f"{current_file_ctx}[Стр. {i}] {safe_truncate(line, 120)}"
        match_line = STRUCT_PREFIX_RE.sub("", line, count=1)
        for cat, rx in COMPILED_PATTERNS.items():
            for match in sorted(set(rx.findall(match_line))):
                if cat == "tags":
                    match = "@" + match
                elif cat in ("urls", "tme_links"):
                    match = match.rstrip(LINK_RSTRIP)
                elif cat == "phones":
                    if DATE_SHAPED_RE.fullmatch(match.strip()):
                        continue
                    match = normalize_phone_key(match)
                    if not match:
                        continue
                elif cat == "cards":
                    match = re.sub(r"[ -]", "", match)
                    if not luhn_ok(match):
                        continue
                elif cat == "crypto_btc":
                    if match.startswith("bc1"):
                        if not btc_bech32_ok(match):
                            continue
                    elif not btc_base58check_ok(match):
                        continue
                if len(entities[cat][match]) < 3:
                    entities[cat][match].append(context_str)
    entities = {c: dict(v) for c, v in entities.items()}
    _derive_accounts(entities)
    # статистика слов — только человеческий текст: без наших маркеров,
    # href-вставок, URL и дат
    body_lines = []
    for l in text.splitlines():
        l = STRUCT_PREFIX_RE.sub("", l, count=1)
        s = l.strip()
        if REACT_LINE_RE.match(s):
            continue
        l = re.sub(r"\[медиа\]", " ", l)
        l = re.sub(r"\[переслано от [^\]]*\]", " ", l)
        l = re.sub(r"\[https?://[^\]]*\]", " ", l)
        l = re.sub(r"https?://\S+", " ", l)
        body_lines.append(l)
    body = "\n".join(body_lines)
    dates = [d for p in (r"\b\d{4}-\d{2}-\d{2}\b", r"\b\d{2}\.\d{2}\.\d{4}\b")
             for d in re.findall(p, body)]
    words = [w for w in WORD_RE.findall(body.lower())
             if w not in STATS_STOP and not w.isdigit()
             and not DATE_WORD_RE.fullmatch(w)]
    return entities, Counter(words).most_common(40), len(dates)

# ==========================================
# ПРОФИЛЬ ЧАТА
# ==========================================
def _stat_key(author_display: str) -> str:
    """Ключ статистики: 'Имя via @pic' и 'Имя [переслано от X...' -> 'Имя'.
    Отображаемое имя остаётся полным в clean.txt; в профиле люди
    склеиваются по базовому имени."""
    a = re.sub(r"\s*via\s+@\S+\s*$", "", author_display)
    a = re.sub(r"\s*\[переслано от.*$", "", a)
    return a.strip() or author_display

def _fmt_duration(sec: float) -> str:
    sec = int(sec)
    if sec < 90:
        return f"{sec} сек"
    if sec < 5400:
        return f"{sec // 60} мин"
    if sec < 172800:
        return f"{sec / 3600:.1f} ч"
    return f"{sec / 86400:.1f} дн"

def _fmt_age(days: float) -> str:
    if days < 2:
        return f"{days * 24:.0f} ч"
    if days < 60:
        return f"{days:.0f} дн"
    if days < 730:
        return f"{days / 30.4:.0f} мес"
    return f"{days / 365.25:.1f} г."

def build_profile(text: str):
    authors = {}
    hours_local, hours_utc, weekdays = Counter(), Counter(), Counter()
    tz_offsets = set()
    responses = defaultdict(list)
    gaps = []
    fwd_count, fwd_ages = 0, []
    react_recv = defaultdict(lambda: defaultdict(int))
    react_given = defaultdict(lambda: defaultdict(int))
    total = media_total = 0
    prev_dt = prev_author = None
    cur_author = None
    first_dt = last_dt = None

    def dt_parse(ts):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                pass
        return None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### SOURCE:") and line.endswith("###"):
            cur_author = None
            prev_dt = prev_author = None
            continue
        rm = REACT_LINE_RE.match(line)
        if rm and cur_author:
            for part in rm.group(1).split(", "):
                if " — " in part:
                    emoji, who = part.split(" — ", 1)
                    emoji = emoji.strip()
                    for r in who.split("; "):
                        react_recv[cur_author][emoji] += 1
                        react_given[r.strip()][emoji] += 1
            continue
        m = MSG_LINE_RE.match(line)
        if not m:
            if cur_author:
                authors[cur_author]["chars"] += len(line)
                if "[медиа]" in line:
                    authors[cur_author]["media"] += 1
                    media_total += 1
            continue
        ts, sign, hh, mm, rest = m.groups()
        dt = dt_parse(ts)
        if dt is None:
            continue
        if ": " in rest:
            author_raw, text_part = rest.split(": ", 1)
        elif rest.endswith(":"):
            author_raw, text_part = rest[:-1], ""
        else:
            author_raw, text_part = rest, ""
        fwd_author = None
        fm = FWD_NOTE_SPLIT_RE.match(author_raw)
        if fm:
            author_raw = fm.group(1)
            fwd_count += 1
            nd = fm.group(2).rsplit(", ", 1)
            fwd_author = nd[0]
            if len(nd) == 2:
                fdt = dt_parse(nd[1])
                if fdt:
                    age = (dt - fdt).total_seconds() / 86400
                    if age >= 0:
                        fwd_ages.append((age, fwd_author))
        author = _stat_key(author_raw.strip())
        a = authors.setdefault(author, {"msgs": 0, "chars": 0, "media": 0,
                                        "first": dt, "last": dt})
        a["msgs"] += 1
        a["first"] = min(a["first"], dt)
        a["last"] = max(a["last"], dt)
        a["chars"] += len(text_part)
        if "[медиа]" in text_part:
            a["media"] += 1
            media_total += 1
        total += 1
        cur_author = author
        if first_dt is None or dt < first_dt:
            first_dt = dt
        if last_dt is None or dt > last_dt:
            last_dt = dt
        hours_local[dt.hour] += 1
        weekdays[dt.weekday()] += 1
        if sign:
            tz_offsets.add(f"UTC{sign}{hh}:{mm}")
            off = (int(hh) * 60 + int(mm)) * (1 if sign == "+" else -1)
            hours_utc[(dt.hour * 60 + dt.minute - off) // 60 % 24] += 1
        else:
            hours_utc[dt.hour] += 1
        if prev_dt is not None:
            delta = (dt - prev_dt).total_seconds()
            if delta > 0:
                gaps.append((delta, prev_dt, dt))
                if prev_author != author and delta < 86400:
                    responses[author].append(delta)
        prev_dt, prev_author = dt, author

    if not total:
        return None
    return {
        "period": [first_dt.strftime("%Y-%m-%d %H:%M"),
                   last_dt.strftime("%Y-%m-%d %H:%M")],
        "tz_offsets": sorted(tz_offsets),
        "totals": {"msgs": total, "media": media_total, "authors": len(authors)},
        "authors": [
            {"name": n, "msgs": a["msgs"], "media": a["media"],
             "avg_len": a["chars"] // max(1, a["msgs"]),
             "first": a["first"].strftime("%Y-%m-%d"),
             "last": a["last"].strftime("%Y-%m-%d")}
            for n, a in sorted(authors.items(), key=lambda kv: (-kv[1]["msgs"], kv[0]))
        ],
        "responses": [
            {"name": n, "median_sec": statistics.median(v), "count": len(v)}
            for n, v in sorted(responses.items(), key=lambda kv: statistics.median(kv[1]))
        ],
        "hours_local": dict(hours_local),
        "hours_utc": dict(hours_utc),
        "weekdays": dict(weekdays),
        "gaps": [[sec, d1.strftime("%Y-%m-%d %H:%M"), d2.strftime("%Y-%m-%d %H:%M")]
                 for sec, d1, d2 in sorted(gaps, reverse=True)[:3]],
        "forwards": {
            "count": fwd_count,
            "ages": [round(a, 3) for a, _ in fwd_ages],
            "max_from": max(fwd_ages)[1] if fwd_ages else None,
        },
        "reactions": {
            "recv": {a: dict(e) for a, e in react_recv.items()},
            "given": {r: dict(e) for r, e in react_given.items()},
        },
    }

def render_profile(p: dict) -> list:
    L = ["", "[ПРОФАЙЛ ЧАТА]", "-" * 40]
    tz = ", ".join(p["tz_offsets"]) if p["tz_offsets"] else "TZ неизвестна"
    L.append(f" Период: {p['period'][0]} — {p['period'][1]} ({tz})")
    t = p["totals"]
    L.append(f" Сообщений: {t['msgs']} (медиа: {t['media']}) | Авторов: {t['authors']}")
    L.append("")
    L.append("АВТОРЫ (по числу сообщений):")
    for a in p["authors"]:
        L.append(f" - {a['name']}: {a['msgs']} сообщ. (медиа {a['media']}), "
                 f"ср. длина {a['avg_len']} симв., {a['first']} — {a['last']}")
    if p["responses"]:
        L.append("")
        L.append("ВРЕМЯ ОТВЕТА (медиана, переходы диалога < 24 ч):")
        for r in p["responses"]:
            L.append(f" - {r['name']}: {_fmt_duration(r['median_sec'])} ({r['count']} ответов)")
    use_local = len(p["tz_offsets"]) <= 1
    hours = p["hours_local"] if use_local else p["hours_utc"]
    if hours:
        L.append("")
        label = f"время экспорта, {tz}" if use_local and p["tz_offsets"] else "UTC"
        L.append(f"АКТИВНОСТЬ ПО ЧАСАМ ({label}):")
        mx = max(hours.values())
        for h in sorted(hours):
            bar = "█" * max(1, round(30 * hours[h] / mx))
            L.append(f" {h:02d} {bar} {hours[h]}")
    if p["weekdays"]:
        L.append("")
        L.append("АКТИВНОСТЬ ПО ДНЯМ НЕДЕЛИ:")
        names = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
        mx = max(p["weekdays"].values())
        for wd in range(7):
            n = p["weekdays"].get(wd, 0)
            if n:
                bar = "█" * max(1, round(20 * n / mx))
                L.append(f" {names[wd]} {bar} {n}")
    if p["gaps"]:
        L.append("")
        L.append("КРУПНЫЕ ПАУЗЫ (топ-3):")
        for sec, d1, d2 in p["gaps"]:
            L.append(f" - {d1} → {d2} ({_fmt_duration(sec)})")
    if p["forwards"]["count"]:
        L.append("")
        ages = p["forwards"]["ages"]
        if ages:
            L.append(f"ПЕРЕСЫЛКИ: {p['forwards']['count']} | возраст контента: "
                     f"медиана {_fmt_age(statistics.median(ages))}, "
                     f"макс {_fmt_age(max(ages))} (от {p['forwards']['max_from']})")
        else:
            L.append(f"ПЕРЕСЫЛКИ: {p['forwards']['count']}")
    if p["reactions"]["recv"]:
        L.append("")
        L.append("РЕАКЦИИ:")
        for author, ems in sorted(p["reactions"]["recv"].items()):
            items = ", ".join(f"{e}×{n}" for e, n in sorted(ems.items()))
            L.append(f" - на сообщения {author}: {items}")
        for reactor, ems in sorted(p["reactions"]["given"].items()):
            items = ", ".join(f"{e}×{n}" for e, n in sorted(ems.items()))
            L.append(f" - ставил(а) {reactor}: {items}")
    return L

def save_entities_report(base_name, entities_dict, top_words, dates_count, out_dir, profile=None):
    payload = {"entities": entities_dict}
    if profile:
        payload["profile"] = profile
    atomic_write(out_dir / f"{base_name}_entities.json",
                 json.dumps(payload, ensure_ascii=False, indent=2))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["КАТЕГОРИЯ", "ЗНАЧЕНИЕ", "КОНТЕКСТ (СТРОКА)"])
    for cat, items in sorted(entities_dict.items()):
        for val, contexts in sorted(items.items()):
            writer.writerow([cat.upper(), csv_safe(val), csv_safe(" | ".join(contexts))])
    atomic_write(out_dir / f"{base_name}_entities.csv", buf.getvalue())

    parts = [
        "Q1 TOOLS REPORT", "=" * 60,
        "Примечания: BTC-адреса валидированы (Base58Check / bech32); ETH и TRX —",
        "кандидаты по формату (чексумма не проверяется); значения нормализованы (NFKC);",
        "телефоны приведены к цифровому ключу.",
    ]
    for cat, items in sorted(entities_dict.items()):
        parts.append(f"\n[{cat.upper()}] (Найдено: {len(items)})")
        if not items:
            parts.append(" - (пусто)")
            continue
        for val, contexts in sorted(items.items()):
            parts.append(f" 🔹 {val}")
            for ctx in contexts:
                parts.append(f"    └ {ctx}")
    parts.append("\n[СТАТИСТИКА]")
    parts.append(f" - Найдено дат в тексте: {dates_count}")
    parts.append("\n[ЧАСТЫЕ СЛОВА]")
    parts.extend(f" - {w}: {n}" for w, n in top_words)
    if profile:
        parts.extend(render_profile(profile))
    atomic_write(out_dir / f"{base_name}_report.txt", "\n".join(parts))
    print(GREEN + f"[+] Отчеты сохранены (TXT, CSV, JSON): {base_name}_..." + RESET)

# ==========================================
# ПАЙПЛАЙНЫ
# ==========================================
def process_file(file, is_html, used_names, run_dir):
    rel_path = file.relative_to(INPUT_DIR)
    print(DIM + f"\n=== ОБРАБОТКА {rel_path} ===" + RESET)
    out_base = get_unique_out_name(file, used_names)
    text = html_to_text(file) if is_html else read_text_smart(file)
    cleaned, orig_c, final_c, perc = clean_text_content(text)
    print(f"[+] Очистка: {orig_c} строк -> {final_c} (удалено {perc}% шума)")
    atomic_write(run_dir / f"{out_base}_clean.txt", cleaned)
    ent_dict, words, dates_c = extract_entities_with_context(cleaned)
    profile = build_profile(cleaned)
    save_entities_report(out_base, ent_dict, words, dates_c, run_dir, profile)

def merge_process(files, is_html, base_name, run_dir):
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    if total > MAX_TOTAL_MERGE_SIZE:
        print(RED + f"[!] Суммарный объем {total // (1024 * 1024)} МБ превышает лимит "
                    f"{MAX_TOTAL_MERGE_SIZE // (1024 * 1024)} МБ. Merge отменен — "
                    f"используйте обработку по-файлово." + RESET)
        return
    all_text = []
    used_names = set()
    for file in files:
        try:
            text = html_to_text(file) if is_html else read_text_smart(file)
            out_name = get_unique_out_name(file, used_names)
            all_text.append(f"\n\n### SOURCE: {out_name} ###\n\n{text}")
        except Exception as e:
            print(RED + f"[!] Пропущен {file.name}: {e}" + RESET)
    if not all_text:
        print(YELLOW + "[-] Нет данных для слияния." + RESET)
        return
    cleaned, orig_c, final_c, perc = clean_text_content("\n".join(all_text))
    print(f"[+] Слияние и очистка: {orig_c} строк -> {final_c} (удалено {perc}% шума)")
    atomic_write(run_dir / f"{base_name}_clean.txt", cleaned)
    ent_dict, words, dates_c = extract_entities_with_context(cleaned)
    profile = build_profile(cleaned)
    save_entities_report(base_name, ent_dict, words, dates_c, run_dir, profile)

def run_pipeline(extensions, is_html, mode=None):
    files = get_files(extensions)
    if not files:
        print(YELLOW + f"\n[!] Положите файлы {extensions} в папку {INPUT_DIR.name} (можно в подпапки)" + RESET)
        return
    if mode is None:
        print("\n[1] Каждый файл отдельно\n[2] Сшить все в один (merge)")
        mode = input("Выбор > ").strip().lstrip("0") or "0"
    kind = "html" if is_html else "txt"
    if mode == "1":
        run_dir = new_run_dir(kind)
        used_names = set()
        for f in files:
            try:
                process_file(f, is_html, used_names, run_dir)
            except Exception as e:
                print(RED + f"[!] Пропущен файл {f.name}: {e}" + RESET)
        print(GREEN + f"\n[+] Прогон завершен. Результаты: output/{run_dir.name}/" + RESET)
    elif mode == "2":
        run_dir = new_run_dir(kind)
        try:
            merge_process(files, is_html, "merged_" + kind, run_dir)
            print(GREEN + f"\n[+] Прогон завершен. Результаты: output/{run_dir.name}/" + RESET)
        except Exception as e:
            print(RED + f"[!] Ошибка при слиянии: {e}" + RESET)
    else:
        print(RED + "[!] Нет такого пункта." + RESET)

# ==========================================
# ПОИСК
# ==========================================
def make_search_matcher(keyword: str, mode: str):
    if mode == "2":
        rx = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
        return lambda line: rx.search(line) is not None
    if mode == "3":
        rx = re.compile(keyword, re.IGNORECASE)
        return lambda line: rx.search(line) is not None
    low = keyword.lower()
    return lambda line: low in line.lower()

def local_search():
    print(YELLOW + "\n[ БЫСТРЫЙ ПОИСК ПО ОТЧЕТАМ ]" + RESET)
    clean_files = [f for f in get_files({".txt"}, folder=OUTPUT_DIR)
                   if "_clean" in f.name and not f.name.startswith("search_")]
    if not clean_files:
        print(RED + "[!] В папке output нет очищенных файлов (*_clean.txt)." + RESET)
        return
    keyword = input("Введите слово для поиска: ").strip()
    if not keyword:
        return
    print(DIM + "Режим: [1] подстрока  [2] целое слово  [3] regex" + RESET)
    mode = input("Режим (Enter = 1) > ").strip() or "1"
    if mode not in ("1", "2", "3"):
        print(RED + "[!] Нет такого режима." + RESET)
        return
    use_ctx = input("Показывать контекст ±2 строки? [y/N] > ").strip().lower() in ("y", "д", "да", "yes")
    try:
        match = make_search_matcher(keyword, mode)
    except re.error as e:
        print(RED + f"[!] Некорректный regex: {e}" + RESET)
        return
    safe_kw = re.sub(r'[\\/:*?"<>|]+', "_", keyword).strip()[:60] or "query"
    run_dir = new_run_dir("search")
    out_path = run_dir / f"search_{safe_kw}.txt"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    total, shown = 0, 0
    print(DIM + "[*] Идет поиск..." + RESET)
    with open(tmp_path, "w", encoding="utf-8") as out:
        for file in clean_files:
            try:
                rel = file.relative_to(OUTPUT_DIR)
                with open(file, "r", encoding="utf-8", errors="ignore") as f:
                    if not use_ctx:
                        for i, line in enumerate(f, 1):
                            if match(line):
                                total += 1
                                if shown < MAX_SEARCH_RESULTS:
                                    out.write(f"[{rel}] Стр {i} | {line.strip()}\n")
                                    shown += 1
                    else:
                        lines = f.readlines()
                        matched = {i for i, l in enumerate(lines) if match(l)}
                        total += len(matched)
                        window = set()
                        for i in matched:
                            window.update(range(max(0, i - 2), min(len(lines), i + 3)))
                        for j in sorted(window):
                            if shown >= MAX_SEARCH_RESULTS:
                                break
                            mark = "→" if j in matched else " "
                            out.write(f"[{rel}] Стр {j + 1} {mark}| {lines[j].rstrip()}\n")
                            shown += 1
            except Exception as e:
                print(RED + f"[!] Ошибка чтения {file.name}: {e}" + RESET)
    if total == 0:
        tmp_path.unlink()
        try:
            run_dir.rmdir()
        except OSError:
            pass
        print(YELLOW + "[-] Ничего не найдено." + RESET)
        return
    os.replace(tmp_path, out_path)
    print(GREEN + f"[+] Найдено совпадений: {total}" + RESET)
    print(GREEN + f"[+] Результаты: output/{run_dir.name}/{out_path.name}" + RESET)
    if total > shown:
        print(YELLOW + f"[!] В файл записаны строки вокруг первых {shown} совпадений (лимит)" + RESET)

# ==========================================
# ЗАПУСК
# ==========================================
def main():
    init_folders()
    while True:
        clear_screen()
        print_menu()
        try:
            choice = input("Выбор > ").strip().lstrip("0") or "0"
            if choice == "1":
                run_pipeline({".html", ".htm"}, True)
            elif choice == "2":
                run_pipeline({".txt"}, False)
            elif choice == "3":
                print("\n[1] Каждый файл отдельно\n[2] Сшить все в один (merge)")
                mode = input("Выбор > ").strip().lstrip("0") or "0"
                if mode not in ("1", "2"):
                    print(RED + "[!] Нет такого пункта." + RESET)
                else:
                    run_pipeline({".html", ".htm"}, True, mode)
                    run_pipeline({".txt"}, False, mode)
            elif choice == "4":
                local_search()
            elif choice == "5":
                try:
                    if os.name == "nt":
                        os.startfile(INPUT_DIR)
                        os.startfile(OUTPUT_DIR)
                    else:
                        opener = "open" if sys.platform == "darwin" else "xdg-open"
                        for d in (INPUT_DIR, OUTPUT_DIR):
                            subprocess.Popen([opener, str(d)])
                    print(GREEN + "\n[+] Рабочие папки открыты." + RESET)
                except Exception as e:
                    print(RED + f"\n[!] Ошибка при открытии папок: {e}" + RESET)
            elif choice == "6":
                print(GREEN + "\n[+] Выход." + RESET)
                break
            else:
                print(RED + "\n[!] Нет такого пункта." + RESET)
            input(DIM + "\nНажми Enter для возврата в меню..." + RESET)
        except (EOFError, KeyboardInterrupt):
            print(GREEN + "\n\n[+] Выход. До встречи!" + RESET)
            break
        except Exception as e:
            print(RED + f"\n[!] Произошла критическая ошибка: {e}" + RESET)
            try:
                input(DIM + "Нажми Enter для продолжения..." + RESET)
            except (EOFError, KeyboardInterrupt):
                break

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(GREEN + "\n\n[+] Принудительный выход (Ctrl+C). До встречи!" + RESET)