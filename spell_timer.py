"""LOL Spell Timer - cửa sổ nhỏ luôn nổi để bấm đếm ngược phép bổ trợ của địch.

Không đọc bộ nhớ game, không can thiệp vào client. Chỉ dùng:
- Live Client Data API chính thức của Riot (https://127.0.0.1:2999) để tự điền tướng / phép địch.
- Data Dragon (CDN công khai của Riot) để tải ảnh tướng, ảnh phép và thời gian hồi.
"""
import ctypes
import gzip
import json
import math
import os
import queue
import re
import ssl
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from functools import lru_cache

API_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
DDRAGON = "https://ddragon.leagueoflegends.com"
APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
CACHE_DIR = os.path.join(APP_DIR, "cache")
# file đi kèm: chạy từ exe PyInstaller thì nằm trong thư mục giải nén tạm sys._MEIPASS
ICON_PATH = os.path.join(getattr(sys, "_MEIPASS", APP_DIR), "assets", "icon.ico")

DEFAULT_CONFIG = {
    "opacity": 0.7,
    "scale": 0.8,  # tỉ lệ giao diện (kéo góc dưới phải hoặc menu ⚙)
    "compact": False,  # chế độ gọn: ẩn tên tướng + dòng điểm hồi
    "ui_version": 2,
    "auto_show": True,  # tự hiện khi vào trận, tự ẩn xuống khay khi hết trận
    "tray_hint_shown": False,
    "x": 40,
    "y": 200,
    "haste_options": [0, 10, 18, 28],
    # điểm hồi cộng thêm chọn tay (ngọc, mảnh chỉ số...) - phần từ trang bị app tự tính
    "ability_haste_options": [0, 5, 8, 10, 15, 18, 20, 25, 30, 40],
    # kỹ năng theo dõi riêng cho từng tướng, vd {"Yasuo": ["W", "R"]}; mặc định chỉ R
    "champion_abilities": {},
    # ghi đè thời gian hồi (giây), vd {"flash": 300}; mặc định lấy theo Data Dragon
    "cd_override": {"smite": 90},
}

# key: (id Data Dragon, tên ngắn, thời gian hồi dự phòng khi chưa tải được Data Dragon)
SPELLS = {
    "flash": ("SummonerFlash", "Flash", 300),
    "ignite": ("SummonerDot", "Ignite", 180),
    "teleport": ("SummonerTeleport", "TP", 300),
    "teleport_unleashed": ("SummonerTeleport", "TP+", 300),  # hồi theo level, xem App.spell_cd
    "heal": ("SummonerHeal", "Heal", 240),
    "barrier": ("SummonerBarrier", "Barrier", 180),
    "exhaust": ("SummonerExhaust", "Exhaust", 240),
    "cleanse": ("SummonerBoost", "Cleanse", 240),
    "ghost": ("SummonerHaste", "Ghost", 240),
    "smite": ("SummonerSmite", "Smite", 90),
    "clarity": ("SummonerMana", "Clarity", 240),
    "mark": ("SummonerSnowball", "Mark", 80),
}

# rawDisplayName của Live API (không phụ thuộc ngôn ngữ client) -> key
SPELL_PATTERNS = [
    ("teleportupgrade", "teleport_unleashed"),
    ("teleport", "teleport"),
    ("flash", "flash"),
    ("summonerdot", "ignite"),
    ("heal", "heal"),
    ("barrier", "barrier"),
    ("exhaust", "exhaust"),
    ("boost", "cleanse"),
    ("haste", "ghost"),
    ("smite", "smite"),
    ("mana", "clarity"),
    ("snowball", "mark"),
]

ROLES = [
    ("TOP", ["flash", "teleport"]),
    ("JGL", ["flash", "smite"]),
    ("MID", ["flash", "ignite"]),
    ("ADC", ["flash", "heal"]),
    ("SUP", ["flash", "exhaust"]),
]
ABILITY_KEYS = "QWER"
DEFAULT_ABILITIES = ["R"]
# Dịch Chuyển Cường Hóa: hồi 330s ở level 1 giảm dần còn 240s ở level 18
UNLEASHED_TP_CD = (330, 240)

# số phần tử mảng cooldown R -> các mốc level mở cấp R tương ứng
ULT_RANK_LEVELS = {
    3: (6, 11, 16),  # đa số tướng
    4: (1, 6, 11, 16),  # Elise, Nidalee, Karma
}
API_ROLE_ORDER = {"TOP": 0, "JUNGLE": 1, "MIDDLE": 2, "BOTTOM": 3, "UTILITY": 4}

HASTE_LABELS = {
    0: "0  - không có",
    10: "10 - Giày Khai Sáng (khi không có dữ liệu trận)",
    18: "18 - Thấu Thị Vũ Trụ",
    28: "28 - Giày + Thấu Thị",
}

# Điểm hồi trong mô tả trang bị của Data Dragon (không có trường số riêng)
ITEM_HASTE_PATTERNS = {
    "ah": r"<attention>\s*(\d+)\s*</attention>\s*Ability Haste",  # chỉ số (HTML gốc)
    "ult": r"(\d+)\s*Ultimate Ability Haste",  # nội tại, vd Malignance
    "basic": r"(\d+)\s*Basic Ability Haste",  # nội tại, vd Giáo Shojin
    "summ": r"(\d+)\s*Summoner Spell Haste",  # vd Giày Khai Sáng
}
NO_HASTE = {"ah": 0, "ult": 0, "basic": 0, "summ": 0}

# Live API chỉ cho biết nhánh ngọc của địch, không có ngọc phụ -> chỉ gợi ý được
RUNE_TREE_HINTS = {
    8300: ("summ", "Nhánh Cảm Hứng: có thể có Thấu Thị Vũ Trụ (+18)"),
    8100: ("ah", "Nhánh Áp Đảo: có thể có Thợ Săn Tối Thượng (hồi R)"),
    8200: ("ah", "Nhánh Pháp Thuật: có thể có Thăng Tiến (+hồi kỹ năng)"),
}

BG = "#14161a"
HEADER_BG = "#0d0f12"
ROW_BG = "#1d2027"
FG = "#d8dde6"
MUTED = "#6b7380"
ACCENT = "#f0b429"

BASE_ICON = 42  # cạnh icon phép ở tỉ lệ 100% (px)
BASE_AVATAR = 43
DIM = 0.3  # độ sáng phần đang hồi
SCALE_RANGE = (0.5, 1.5)
SCALE_OPTIONS = [0.6, 0.7, 0.8, 0.9, 1.0, 1.15, 1.3]
OPACITY_OPTIONS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
# font có tên: đổi cỡ một lần, mọi widget dùng font đó tự cập nhật
FONT_SPECS = {
    "title": (9, "bold"), "text": (8, "normal"), "bold": (8, "bold"), "name": (9, "bold"),
    "timer": (10, "bold"), "badge": (7, "bold"), "plus": (11, "bold"), "avatar": (12, "normal"),
}


@lru_cache(maxsize=8)
def sweep_angles(size):
    """Góc của từng điểm ảnh, tính từ 12 giờ theo chiều kim đồng hồ - cho hiệu ứng quét."""
    return [math.degrees(math.atan2(x + 0.5 - size / 2, size / 2 - y - 0.5)) % 360
            for y in range(size) for x in range(size)]


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user = json.load(f)
        override = user.pop("cd_override", {})
        if "ui_version" not in user:  # config bản cũ: áp độ trong suốt mặc định mới
            user.pop("opacity", None)
        cfg.update({k: v for k, v in user.items() if k in DEFAULT_CONFIG})  # bỏ khóa cũ
        cfg["cd_override"].update(override)
    except FileNotFoundError:
        pass
    except Exception as e:
        print("Không đọc được config.json, dùng mặc định:", e)
        return cfg
    save_config(cfg)
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def spell_key(spell):
    raw = (spell or {}).get("rawDisplayName", "").lower()
    for pattern, key in SPELL_PATTERNS:
        if pattern in raw:
            return key
    return None


def api_spell_keys(player):
    spells = player.get("summonerSpells", {})
    return [spell_key(spells.get(name)) for name in ("summonerSpellOne", "summonerSpellTwo")]


def normalize(text):
    return "".join(c for c in (text or "").lower() if c.isalnum())


def fmt_time(seconds):
    seconds = max(0, int(seconds + 0.999))
    return f"{seconds // 60}:{seconds % 60:02d}"


def parse_item_haste(item_json):
    """Đọc điểm hồi từ mô tả từng trang bị. Món có điểm hồi phụ thuộc chỉ số khác
    (vd Endless Hunger) không tính được nên bỏ qua."""
    result = {}
    for item_id, item in item_json["data"].items():
        html = item.get("description", "")
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
        haste = {}
        for kind, pattern in ITEM_HASTE_PATTERNS.items():
            match = re.search(pattern, html if kind == "ah" else text)
            if match:
                haste[kind] = int(match.group(1))
        if haste:
            result[item_id] = haste
    return result


class Assets:
    """Danh sách tướng, ảnh và thời gian hồi từ Data Dragon, lưu cache trong thư mục cache/."""

    def __init__(self):
        for sub in ("champion", "spell"):
            os.makedirs(os.path.join(CACHE_DIR, sub), exist_ok=True)
        self.champions = {}  # id -> tên hiển thị
        self.spell_cd = {}  # id Data Dragon -> giây
        self.abilities = {}  # id tướng -> 4 x {"name", "cd": [giây theo cấp], "img"} (Q W E R)
        self.item_haste = {}  # id trang bị (str) -> {"ah", "ult", "basic", "summ"} (chỉ món có)
        self.version = None
        self.pending_icons = set()
        self.changed = 0
        self.lock = threading.Lock()
        self.images = {}
        self.load_cached_json()
        threading.Thread(target=self.sync, daemon=True).start()

    def get(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "LOLSpellTimer/1.0",
                                                   "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            return gzip.decompress(body) if r.headers.get("Content-Encoding") == "gzip" else body

    def save(self, rel_path, content):
        path = os.path.join(CACHE_DIR, rel_path)
        with open(path + ".tmp", "wb") as f:
            f.write(content)
        os.replace(path + ".tmp", path)

    def load_cached_json(self):
        try:
            with open(os.path.join(CACHE_DIR, "champion.json"), encoding="utf-8") as f:
                data = json.load(f)["data"]
            self.champions = {cid: c["name"] for cid, c in data.items()}
            with open(os.path.join(CACHE_DIR, "summoner.json"), encoding="utf-8") as f:
                data = json.load(f)["data"]
            self.spell_cd = {sid: s["cooldown"][0] for sid, s in data.items()}
            with open(os.path.join(CACHE_DIR, "abilities.json"), encoding="utf-8") as f:
                self.abilities = json.load(f)
            with open(os.path.join(CACHE_DIR, "item_haste.json"), encoding="utf-8") as f:
                self.item_haste = json.load(f)
            with open(os.path.join(CACHE_DIR, "version.txt"), encoding="utf-8") as f:
                self.version = f.read().strip()
        except (OSError, ValueError, KeyError):
            pass

    def bump(self):
        with self.lock:
            self.changed += 1

    def sync(self):
        try:
            version = json.loads(self.get(f"{DDRAGON}/api/versions.json"))[0]
            version_file = os.path.join(CACHE_DIR, "version.txt")
            cached = open(version_file).read().strip() if os.path.exists(version_file) else ""
            if version != cached or not self.champions or not self.abilities \
                    or not self.item_haste:
                for name in ("champion", "summoner"):
                    self.save(f"{name}.json",
                              self.get(f"{DDRAGON}/cdn/{version}/data/en_US/{name}.json"))
                # championFull.json (~2MB) chỉ để lấy Q/W/E/R, lưu gọn lại thành abilities.json
                full = json.loads(self.get(f"{DDRAGON}/cdn/{version}/data/en_US/championFull.json"))
                abilities = {cid: [{"name": sp["name"], "cd": sp["cooldown"],
                                    "img": sp["image"]["full"].rsplit(".", 1)[0]}
                                   for sp in c["spells"][:4]]
                             for cid, c in full["data"].items()}
                self.save("abilities.json", json.dumps(abilities).encode("utf-8"))
                items = json.loads(self.get(f"{DDRAGON}/cdn/{version}/data/en_US/item.json"))
                self.save("item_haste.json", json.dumps(parse_item_haste(items)).encode("utf-8"))
                with open(version_file, "w") as f:
                    f.write(version)
                self.load_cached_json()
                self.bump()
        except Exception as e:
            print("Không tải được Data Dragon:", e)
            return

        jobs = [("champion", cid) for cid in self.champions]
        jobs += [("spell", sid) for sid, _, _ in SPELLS.values()]
        jobs += [("spell", a[3]["img"]) for a in self.abilities.values()]  # Q/W/E tải khi cần
        jobs = [j for j in jobs if not os.path.exists(os.path.join(CACHE_DIR, j[0], j[1] + ".png"))]

        def download(job):
            kind, name = job
            try:
                self.save(f"{kind}/{name}.png",
                          self.get(f"{DDRAGON}/cdn/{version}/img/{kind}/{name}.png"))
                self.bump()
            except Exception:
                pass

        with ThreadPoolExecutor(8) as pool:
            list(pool.map(download, jobs))

    def ensure_icon(self, name):
        """Tải icon kỹ năng ở luồng nền nếu chưa có (Q/W/E chỉ tải khi được thêm vào)."""
        path = os.path.join(CACHE_DIR, "spell", name + ".png")
        if os.path.exists(path) or name in self.pending_icons or not self.version:
            return
        self.pending_icons.add(name)

        def download():
            try:
                self.save(f"spell/{name}.png",
                          self.get(f"{DDRAGON}/cdn/{self.version}/img/spell/{name}.png"))
                self.bump()
            except Exception:
                pass
            finally:
                self.pending_icons.discard(name)

        threading.Thread(target=download, daemon=True).start()

    def image(self, kind, name, factor):
        """PhotoImage thu nhỏ `factor` lần, hoặc None nếu chưa tải về. Chỉ gọi từ luồng UI."""
        if not name:
            return None
        cache_key = (kind, name, factor)
        if cache_key in self.images:
            return self.images[cache_key]
        path = os.path.join(CACHE_DIR, kind, name + ".png")
        if not os.path.exists(path):
            return None
        try:
            img = tk.PhotoImage(file=path).subsample(factor)
        except tk.TclError:
            return None
        self.images[cache_key] = img
        return img

    def champion_image(self, champ_id, factor=3):  # ảnh gốc 128px -> 43px (bảng chọn tướng)
        return self.image("champion", champ_id, factor)

    def scaled_image(self, kind, name, size):
        """PhotoImage thu về đúng `size` px (subsample chỉ chia được số nguyên)."""
        cache_key = ("scaled", kind, name, size)
        if cache_key not in self.images:
            pixels = self.pixels(kind, name, size)
            if not pixels:
                return None
            img = tk.PhotoImage(width=size, height=size)
            img.put(" ".join("{" + " ".join(pixels[0][y * size:(y + 1) * size]) + "}"
                             for y in range(size)))
            self.images[cache_key] = img
        return self.images[cache_key]

    def spell_image(self, key, factor=4):  # ảnh gốc 64px -> 16px (icon trong menu)
        return self.image("spell", SPELLS[key][0], factor)

    def icon_pixels(self, name, size):
        return self.pixels("spell", name, size)

    def pixels(self, kind, name, size):
        """Màu từng điểm ảnh của cache/<kind>/<name>.png thu về size×size: (sáng, tối),
        hoặc None nếu chưa tải về."""
        cache_key = ("pixels", kind, name, size)
        if cache_key in self.images:
            return self.images[cache_key]
        rows_key = ("rows", kind, name)
        if rows_key not in self.images:  # đọc pixel gốc một lần, dùng lại khi đổi tỉ lệ
            src = self.image(kind, name, 1)
            if not src:
                return None
            self.images[rows_key] = [[int(c[1:], 16) for c in src.tk.splitlist(row)]
                                     for row in src.tk.splitlist(src.tk.call(src.name, "data"))]
        rows = self.images[rows_key]
        h, w = len(rows), len(rows[0])
        bright, dark = [], []
        for y in range(size):  # thu nhỏ bằng cách lấy trung bình từng vùng
            y0, y1 = y * h // size, max(y * h // size + 1, (y + 1) * h // size)
            for x in range(size):
                x0, x1 = x * w // size, max(x * w // size + 1, (x + 1) * w // size)
                area = [rows[yy][xx] for yy in range(y0, y1) for xx in range(x0, x1)]
                r, g, b = (sum((p >> s) & 255 for p in area) // len(area) for s in (16, 8, 0))
                bright.append(f"#{r:02x}{g:02x}{b:02x}")
                dark.append(f"#{int(r * DIM):02x}{int(g * DIM):02x}{int(b * DIM):02x}")
        self.images[cache_key] = (bright, dark)
        return bright, dark

    def find_champion(self, player):
        raw = player.get("rawChampionName", "")
        cid = raw.rsplit("_", 1)[-1] if raw else ""
        if cid in self.champions:
            return cid
        wanted = normalize(player.get("championName"))
        for cid, name in self.champions.items():
            if wanted in (normalize(cid), normalize(name)):
                return cid
        return cid or player.get("championName")


class Poller(threading.Thread):
    """Gọi Live Client API mỗi 2 giây ở luồng nền để UI không bị đơ."""

    def __init__(self, mock_path=None):
        super().__init__(daemon=True)
        self.mock_path = mock_path
        self.lock = threading.Lock()
        self.latest = None  # (data | None, monotonic time)
        self.seq = 0
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # API dùng chứng chỉ tự ký của Riot
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx)
        )

    def fetch(self):
        if self.mock_path:
            with open(self.mock_path, encoding="utf-8") as f:
                return json.load(f)
        with self.opener.open(API_URL, timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8"))

    def run(self):
        while True:
            try:
                data = self.fetch()
                if "allPlayers" not in data:
                    data = None
            except Exception:
                data = None
            with self.lock:
                self.latest = (data, time.monotonic())
                self.seq += 1
            time.sleep(2)


# ---------- focus: click vào app không lấy focus (bàn phím) khỏi game ----------
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000  # cờ mà bàn phím ảo của Windows cũng dùng
try:
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
except (AttributeError, OSError):  # không phải Windows
    user32 = None


def window_handle(window):
    """HWND thật của cửa sổ Tk (khung ngoài cùng)."""
    return int(window.wm_frame(), 16)


def set_no_activate(window):
    """Click vào cửa sổ vẫn bấm được nút nhưng Windows không chuyển focus sang nó.
    Phải gọi lại sau mỗi lần đổi attributes (-alpha, -topmost) vì Tk ghi đè extended style."""
    if user32:
        hwnd = window_handle(window)
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)


def foreground_window():
    return user32.GetForegroundWindow() if user32 else None


def set_foreground(hwnd):
    if user32 and hwnd:
        user32.SetForegroundWindow(hwnd)


# ---------- icon ở khay hệ thống (góc phải taskbar): Win32 thuần qua ctypes ----------
WM_NULL, WM_DESTROY, WM_CLOSE = 0x0000, 0x0002, 0x0010
WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
WM_TRAY = 0x8000 + 1  # WM_APP + 1: Windows gửi về khi có thao tác chuột trên icon
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
MF_STRING, MF_CHECKED, MF_SEPARATOR = 0x0, 0x8, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100
LRESULT = ctypes.c_ssize_t


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON),
    ]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                             wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class TrayIcon(threading.Thread):
    """Icon ở khay hệ thống. Chạy vòng lặp message Win32 ở luồng riêng; mọi thao tác của
    người dùng được đẩy vào `events` (queue) để luồng UI Tk tự lấy ra xử lý.
    `menu_items()` trả về [(id, nhãn, có_dấu_tích)], id None = đường kẻ ngang."""

    def __init__(self, tooltip, icon_path, menu_items):
        super().__init__(daemon=True)
        self.tooltip = tooltip
        self.icon_path = icon_path
        self.menu_items = menu_items
        self.events = queue.Queue()
        self.hwnd = None
        self.taskbar_created = None  # wndproc nhận message ngay trong lúc CreateWindowExW
        self.ready = threading.Event()
        # WinDLL riêng để argtypes không đụng tới cấu hình user32 ở phần khác
        self.u = u = ctypes.WinDLL("user32", use_last_error=True)
        self.shell = ctypes.WinDLL("shell32")
        u.DefWindowProcW.restype = LRESULT
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                     wintypes.LPARAM]
        u.CreateWindowExW.restype = wintypes.HWND
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                      wintypes.HINSTANCE, wintypes.LPVOID]
        u.LoadImageW.restype = wintypes.HANDLE
        u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.LoadIconW.restype = wintypes.HICON
        u.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
        u.CreatePopupMenu.restype = wintypes.HMENU
        u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                                  wintypes.LPCWSTR]
        u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                   wintypes.LPARAM]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.DestroyMenu.argtypes = [wintypes.HMENU]
        u.DestroyWindow.argtypes = [wintypes.HWND]
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                                  wintypes.UINT]
        self.shell.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                                 ctypes.POINTER(NOTIFYICONDATAW)]

    def start(self):
        super().start()
        if not self.ready.wait(3) or not self.hwnd:
            raise OSError("không tạo được icon khay hệ thống")
        return self

    def icon_data(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd, nid.uID, nid.uFlags = self.hwnd, 1, flags
        return nid

    def add_icon(self):
        nid = self.icon_data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = self.tooltip
        return self.shell.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def notify(self, title, text):
        """Bong bóng thông báo của Windows cạnh icon."""
        nid = self.icon_data(NIF_INFO)
        nid.szInfoTitle, nid.szInfo, nid.dwInfoFlags = title, text, 1  # NIIF_INFO
        self.shell.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def stop(self):
        if self.hwnd:
            self.u.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self.join(2)

    def run(self):
        u = self.u
        hinstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        self._wndproc = WNDPROC(self.wndproc)  # giữ tham chiếu, nếu không sẽ bị thu gom
        wc = WNDCLASSW(lpfnWndProc=self._wndproc, hInstance=hinstance,
                       lpszClassName="LOLSpellTimerTray")
        u.RegisterClassW(ctypes.byref(wc))
        # cửa sổ ẩn (không bao giờ hiện) chỉ để nhận message từ icon
        self.hwnd = u.CreateWindowExW(0, "LOLSpellTimerTray", "LOL Spell Timer tray", 0,
                                      0, 0, 0, 0, None, None, hinstance, None)
        # Explorer khởi động lại (vd crash) sẽ phát message này: phải thêm lại icon
        self.taskbar_created = u.RegisterWindowMessageW("TaskbarCreated")
        size = u.GetSystemMetrics(49)  # SM_CXSMICON: cỡ icon nhỏ theo DPI hiện tại
        self.hicon = (u.LoadImageW(None, self.icon_path, 1, size, size, 0x10)  # LR_LOADFROMFILE
                      if os.path.exists(self.icon_path) else None) \
            or u.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION
        if self.hwnd and not self.add_icon():
            self.hwnd = None
        self.ready.set()
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    def wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event == WM_LBUTTONUP:
                self.events.put("toggle")
            elif event == WM_RBUTTONUP:
                self.show_menu()
            return 0
        if msg == self.taskbar_created:
            self.add_icon()
        elif msg == WM_CLOSE:
            self.shell.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.icon_data(0)))
            self.u.DestroyWindow(hwnd)
            return 0
        elif msg == WM_DESTROY:
            self.u.PostQuitMessage(0)
            return 0
        return self.u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def show_menu(self):
        u = self.u
        menu = u.CreatePopupMenu()
        for item_id, label, checked in self.menu_items():
            if item_id is None:
                u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                u.AppendMenuW(menu, MF_STRING | (MF_CHECKED if checked else 0), item_id, label)
        point = wintypes.POINT()
        u.GetCursorPos(ctypes.byref(point))
        u.SetForegroundWindow(self.hwnd)  # bắt buộc để menu tự đóng khi click ra ngoài
        chosen = u.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
                                  point.x, point.y, 0, self.hwnd, None)
        u.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        u.DestroyMenu(menu)
        if chosen:
            self.events.put(chosen)


def fixed_box(parent, width, height, **pack):
    """Khung kích thước cố định (Label tính width theo ký tự khi không có ảnh)."""
    box = tk.Frame(parent, width=width, height=height, bg=parent.cget("bg"))
    box.pack_propagate(False)
    box.pack(side="left", **pack)
    return box


def make_menu(root):
    return tk.Menu(root, tearoff=0, bg=ROW_BG, fg=FG, activebackground="#2d3340",
                   activeforeground=FG, font=("Segoe UI", 9), bd=0)


class TimerSlot:
    """Ô icon có đếm ngược, hiệu ứng tối + kim quét như trong game.
    Lớp con quyết định icon, tên, thời gian hồi và menu chuột phải."""
    BORDER = ROW_BG
    name = "?"

    def __init__(self, row, parent):
        self.row = row
        self.app = row.app
        self.ready_at = None  # monotonic
        self.total = 1  # tổng thời gian hồi của lần đếm hiện tại
        self.ready_game_time = None
        self.pixels = None
        size, mid = self.app.icon_size, self.app.icon_size / 2
        fonts = self.app.fonts
        self.frame = tk.Frame(parent, bg=self.BORDER)
        self.frame.pack(side="left", padx=2, pady=2)
        self.canvas = tk.Canvas(self.frame, width=size, height=size, bg="#2a2e37",
                                highlightthickness=0, cursor="hand2")
        self.canvas.pack(padx=2, pady=2)
        self.photo = tk.PhotoImage(width=size, height=size)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.hand = self.canvas.create_line(mid, mid, mid, 0, fill="#f3e3b0", width=2,
                                            state="hidden")
        self.shadow = self.canvas.create_text(mid + 1, mid + 1, font=fonts["timer"],
                                              fill="#000000")
        self.text = self.canvas.create_text(mid, mid, font=fonts["timer"], fill="#ffffff")
        self.badge_shadow = self.canvas.create_text(size, size, anchor="se",
                                                    font=fonts["badge"], fill="#000000")
        self.badge_text = self.canvas.create_text(size - 1, size - 1, anchor="se",
                                                  font=fonts["badge"], fill=ACCENT)
        self.canvas.bind("<Button-1>", lambda e: self.toggle())
        self.canvas.bind("<Button-3>", self.show_menu)
        self._last_render = None

    # --- lớp con ghi đè ---
    def cooldown(self):
        """Thời gian hồi thực tế (giây), hoặc None nếu chưa đếm được."""
        raise NotImplementedError

    def load_pixels(self):
        raise NotImplementedError

    def badge(self):
        return ""

    def show_menu(self, event):
        raise NotImplementedError

    # --- dùng chung ---
    def resize(self):
        size, mid = self.app.icon_size, self.app.icon_size / 2
        self.canvas.config(width=size, height=size)
        self.photo.config(width=size, height=size)
        self.canvas.coords(self.shadow, mid + 1, mid + 1)
        self.canvas.coords(self.text, mid, mid)
        self.canvas.coords(self.badge_shadow, size, size)
        self.canvas.coords(self.badge_text, size - 1, size - 1)
        self.refresh_image()

    def refresh_image(self):
        self.pixels = self.load_pixels()
        self._last_render = None
        self.render()

    def toggle(self):
        if self.remaining():
            self.reset()  # click lại khi đang hồi = hủy (bấm nhầm)
        else:
            self.start()

    def start(self):
        cd = self.cooldown()
        if not cd:
            return
        self.total = cd
        self.ready_at = time.monotonic() + cd
        game_time = self.app.estimated_game_time()
        self.ready_game_time = game_time + cd if game_time is not None else None
        self.render()

    def reset(self):
        self.ready_at = None
        self.ready_game_time = None
        self.render()

    def add_cancel(self, menu):
        if self.ready_at is not None:
            menu.add_command(label="Hủy đếm ngược", command=self.reset)
            menu.add_separator()

    def remaining(self):
        if self.ready_at is None:
            return 0
        left = self.ready_at - time.monotonic()
        if left <= 0:
            self.ready_at = None
            self.ready_game_time = None
            return 0
        return left

    def render(self):
        left = self.remaining()
        sweep = int((1 - left / self.total) * 360) if left else 360  # phần đã hồi (độ)
        timer = (fmt_time(left) if left >= 60 else str(int(left + 0.999))) if left else ""
        badge = self.badge()
        size = self.app.icon_size
        state = (self.pixels is not None, sweep, timer, badge, size)
        if state == self._last_render:
            return
        self._last_render = state

        if self.pixels:
            bright, dark = self.pixels
            if sweep >= 360:
                colors = bright
            else:
                colors = [b if a < sweep else d
                          for a, b, d in zip(sweep_angles(size), bright, dark)]
            self.photo.put(" ".join("{" + " ".join(colors[y * size:(y + 1) * size]) + "}"
                                    for y in range(size)))
        else:
            self.photo.blank()
            timer = timer or self.name  # chưa có ảnh: hiện tên

        if left:
            mid, rad = size / 2, math.radians(sweep)
            self.canvas.coords(self.hand, mid, mid, mid + size * math.sin(rad),
                               mid - size * math.cos(rad))
        self.canvas.itemconfig(self.hand, state="normal" if left and self.pixels else "hidden")
        font = self.app.fonts["timer" if left or self.pixels else "bold"]
        for item in (self.shadow, self.text):
            self.canvas.itemconfig(item, text=timer, font=font)
        for item in (self.badge_shadow, self.badge_text):
            self.canvas.itemconfig(item, text=badge)


class SpellSlot(TimerSlot):
    """Phép bổ trợ (Flash, Ignite...)."""

    def __init__(self, row, parent, key):
        super().__init__(row, parent)
        self.key = key
        self.refresh_image()

    @property
    def name(self):
        return SPELLS[self.key][1]

    def set_key(self, key, keep_timer=False):
        self.key = key
        if not keep_timer:
            self.reset()
        self.refresh_image()

    def cooldown(self):
        return self.app.spell_cd(self.key, self.row.level) * 100 / (100 + self.row.summoner_haste())

    def load_pixels(self):
        return self.app.assets.icon_pixels(SPELLS[self.key][0], self.app.icon_size)

    def show_menu(self, event):
        menu = make_menu(self.app.root)
        self.add_cancel(menu)
        for key, (_, name, _) in SPELLS.items():
            icon = self.app.assets.spell_image(key, 4)
            extra = {"image": icon, "compound": "left"} if icon else {}
            mark = "  ✓" if key == self.key else ""
            cd = fmt_time(self.app.spell_cd(key, self.row.level))
            menu.add_command(label=f" {name}  ({cd}){mark}",
                             command=lambda k=key: self.set_key(k, keep_timer=True), **extra)
        menu.add_separator()
        menu.add_command(label="Bỏ khỏi bảng theo dõi", command=lambda: self.row.remove_slot(self))
        self.app.popup(menu, event)


class AbilitySlot(TimerSlot):
    """Kỹ năng Q / W / E / R của tướng đang chọn: hồi theo cấp kỹ năng + điểm hồi kỹ năng."""
    BORDERS = {"Q": "#4a6a8f", "W": "#4a6a8f", "E": "#4a6a8f", "R": "#c8aa6e"}

    def __init__(self, row, parent, letter):
        self.letter = letter
        self.BORDER = self.BORDERS[letter]
        super().__init__(row, parent)
        self.rank_var = tk.IntVar(value=1)
        self.auto_rank = None  # cấp R tự tính từ level lần gần nhất
        self.refresh_image()

    @property
    def name(self):
        return self.letter

    def data(self):
        abilities = self.app.assets.abilities.get(self.row.champ_id)
        return abilities[ABILITY_KEYS.index(self.letter)] if abilities else None

    def rank(self):
        data = self.data()
        return min(self.rank_var.get(), len(data["cd"])) if data else 1

    def cooldown(self, rank=None, extra=None):
        data = self.data()
        if not data:
            return None
        haste = self.row.ability_haste_for(self.letter, extra)
        return data["cd"][(rank or self.rank()) - 1] * 100 / (100 + haste)

    def load_pixels(self):
        data = self.data()
        if not data:
            return None
        self.app.assets.ensure_icon(data["img"])
        return self.app.assets.icon_pixels(data["img"], self.app.icon_size)

    def badge(self):
        data = self.data()
        return f"{self.letter}{self.rank()}" if data and len(data["cd"]) > 1 else self.letter

    def show_menu(self, event):
        menu = make_menu(self.app.root)
        self.add_cancel(menu)
        data = self.data()
        if data:
            menu.add_command(label=f"Cấp {self.letter}:", state="disabled")
            for rank in range(1, len(data["cd"]) + 1):
                menu.add_radiobutton(
                    label=f"Cấp {rank}   -   {fmt_time(self.cooldown(rank))}", value=rank,
                    variable=self.rank_var, selectcolor=ACCENT, command=self.row.render_hastes)
            menu.add_separator()
            menu.add_cascade(label="Điểm hồi kỹ năng", menu=self.row.ability_haste_menu(menu))
            menu.add_separator()
        menu.add_command(label="Bỏ khỏi bảng theo dõi", command=lambda: self.row.remove_slot(self))
        self.app.popup(menu, event)

    def update_level(self, level):
        """Tự chọn cấp R theo level địch (có trên bảng Tab); chỉ đổi khi vừa lên mốc mới."""
        data = self.data()
        if self.letter != "R" or not data or not level:
            return
        thresholds = ULT_RANK_LEVELS.get(len(data["cd"]))
        if not thresholds:
            return
        rank = max(1, sum(level >= lv for lv in thresholds))
        if rank != self.auto_rank:
            self.auto_rank = rank
            self.rank_var.set(rank)
            self.render()


class EnemyRow:
    def __init__(self, app, parent, role, spell_keys):
        self.app = app
        self.role = role
        self.champ_id = None
        self.player_id = None  # riotId của địch khi tự nhận từ trận
        self.item_haste = dict(NO_HASTE)  # tự tính từ trang bị địch đang có
        self.rune_trees = set()  # nhánh ngọc địch (Live API)
        self.level = None  # level địch đọc từ trận
        self.api_spells = None  # phép bổ trợ API báo lần trước
        self.haste = tk.IntVar(value=0)  # điểm hồi phép bổ trợ cộng thêm (chọn tay)
        self.ability_haste = tk.IntVar(value=0)  # điểm hồi kỹ năng cộng thêm (chọn tay)

        self.frame = tk.Frame(parent, bg=ROW_BG)
        self.frame.pack(fill="x", pady=1)
        fonts = app.fonts
        tk.Label(self.frame, text=role, width=4, font=fonts["bold"],
                 bg=ROW_BG, fg=MUTED).pack(side="left")

        self.avatar_box = fixed_box(self.frame, app.avatar_size, app.avatar_size,
                                    padx=(0, 4), pady=3)
        self.avatar = tk.Label(self.avatar_box, bg="#2a2e37", fg=MUTED, text="+", bd=0,
                               font=fonts["avatar"], cursor="hand2")
        self.avatar.pack(fill="both", expand=True)

        info = self.info = tk.Frame(self.frame, bg=ROW_BG)
        info.pack(side="left", fill="y", padx=(0, 2))
        self.name_label = tk.Label(info, text="Chọn tướng", width=11, anchor="w",
                                   font=fonts["name"], bg=ROW_BG, fg=MUTED,
                                   cursor="hand2")
        self.name_label.pack(anchor="w", pady=(2, 0))
        hastes = tk.Frame(info, bg=ROW_BG)  # "⚡ 10  ◆ 20" trên một dòng cho gọn
        hastes.pack(anchor="w")
        self.haste_label = tk.Label(hastes, font=fonts["text"], bg=ROW_BG, cursor="hand2",
                                    padx=0, pady=0)
        self.haste_label.pack(side="left", padx=(0, 6))
        self.ah_label = tk.Label(hastes, font=fonts["text"], bg=ROW_BG, cursor="hand2",
                                 padx=0, pady=0)
        self.ah_label.pack(side="left")

        for w in (self.avatar, self.name_label):
            w.bind("<Button-1>", lambda e: self.app.open_picker(self))
        self.haste_label.bind("<Button-1>", lambda e: self.app.popup(
            self.haste_menu(self.app.root), e))
        self.avatar.bind("<Button-3>", self.show_avatar_menu)  # chế độ gọn vẫn chỉnh được
        self.ah_label.bind("<Button-1>", lambda e: self.app.popup(
            self.ability_haste_menu(self.app.root), e))

        self.slot_area = tk.Frame(self.frame, bg=ROW_BG)
        self.slot_area.pack(side="left")
        self.add_button = tk.Label(self.slot_area, text="+", font=fonts["plus"],
                                   bg=ROW_BG, fg=MUTED, cursor="hand2", padx=4)
        self.add_button.bind("<Button-1>", self.show_add_menu)
        self.add_button.bind("<Enter>", lambda e: self.add_button.config(fg=ACCENT))
        self.add_button.bind("<Leave>", lambda e: self.add_button.config(fg=MUTED))

        self.spell_slots = [SpellSlot(self, self.slot_area, key) for key in spell_keys]
        self.ability_slots = []
        self.layout()
        self.set_compact(app.cfg["compact"])
        self.render_hastes()
        self.refresh_avatar()

    @property
    def slots(self):
        return self.spell_slots + self.ability_slots

    # ---------- thêm / bỏ ô ----------
    def layout(self):
        """Xếp lại các ô theo thứ tự: phép bổ trợ, Q, W, E, R, nút +."""
        self.ability_slots.sort(key=lambda s: ABILITY_KEYS.index(s.letter))
        for slot in self.slots:
            slot.frame.pack_forget()
        self.add_button.pack_forget()
        for slot in self.slots:
            slot.frame.pack(side="left", padx=2, pady=2)
        self.add_button.pack(side="left", fill="y")

    def tracked_letters(self):
        return [s.letter for s in self.ability_slots]

    def add_ability(self, letter, save=True):
        if letter in self.tracked_letters():
            return
        self.ability_slots.append(AbilitySlot(self, self.slot_area, letter))
        self.ability_slots[-1].update_level(self.level)
        self.layout()
        if save:
            self.save_preference()

    def add_spell(self, key):
        self.spell_slots.append(SpellSlot(self, self.slot_area, key))
        self.layout()

    def remove_slot(self, slot):
        slot.frame.destroy()
        if slot in self.spell_slots:
            self.spell_slots.remove(slot)
        else:
            self.ability_slots.remove(slot)
            self.save_preference()
        self.layout()

    def save_preference(self):
        """Nhớ danh sách kỹ năng theo dõi cho tướng này (vd Yasuo: W + R)."""
        if self.champ_id:
            self.app.cfg["champion_abilities"][self.champ_id] = self.tracked_letters()
            save_config(self.app.cfg)

    def set_abilities(self, letters):
        for slot in self.ability_slots:
            slot.frame.destroy()
        self.ability_slots = []
        for letter in letters:
            self.add_ability(letter, save=False)
        self.layout()

    def set_spells(self, keys):
        """Đặt lại đúng các phép bổ trợ (dùng khi sang trận mới)."""
        while len(self.spell_slots) > len(keys):
            self.spell_slots.pop().frame.destroy()
        while len(self.spell_slots) < len(keys):
            self.spell_slots.append(SpellSlot(self, self.slot_area, keys[len(self.spell_slots)]))
        for slot, key in zip(self.spell_slots, keys):
            slot.set_key(key)
        self.layout()

    def show_add_menu(self, event):
        menu = make_menu(self.app.root)
        abilities = self.app.assets.abilities.get(self.champ_id)
        if abilities:
            menu.add_command(label=f"Thêm kỹ năng của {self.champ_name()}:", state="disabled")
            for letter, data in zip(ABILITY_KEYS, abilities):
                if letter in self.tracked_letters():
                    continue
                cds = data["cd"]
                cd_text = f"{cds[0]:g}s" if min(cds) == max(cds) else f"{cds[0]:g}s → {cds[-1]:g}s"
                icon = self.app.assets.image("spell", data["img"], 4)
                extra = {"image": icon, "compound": "left"} if icon else {}
                menu.add_command(label=f" {letter}  -  {data['name']}  ({cd_text})",
                                 command=lambda l=letter: self.add_ability(l), **extra)
                self.app.assets.ensure_icon(data["img"])
        else:
            menu.add_command(label="Chọn tướng để thêm kỹ năng", state="disabled")
        if len(self.spell_slots) < 2:
            spells = make_menu(menu)
            for key, (_, name, _) in SPELLS.items():
                spells.add_command(label=name, command=lambda k=key: self.add_spell(k))
            menu.add_separator()
            menu.add_cascade(label="Thêm phép bổ trợ", menu=spells)
        self.app.popup(menu, event)

    # ---------- tướng ----------
    def champ_name(self):
        if not self.champ_id:
            return self.role
        return self.app.assets.champions.get(self.champ_id, self.champ_id)

    def set_champion(self, champ_id):
        if champ_id != self.champ_id:
            self.champ_id = champ_id
            prefs = self.app.cfg["champion_abilities"]
            self.set_abilities(prefs.get(champ_id, DEFAULT_ABILITIES) if champ_id else [])
        self.refresh_images()

    def set_compact(self, compact):
        if compact:
            self.info.pack_forget()
        else:
            self.info.pack(side="left", fill="y", padx=(0, 2), after=self.avatar_box)

    def resize(self):
        size = self.app.avatar_size
        self.avatar_box.config(width=size, height=size)
        self.refresh_avatar()
        for slot in self.slots:
            slot.resize()

    def refresh_avatar(self):
        img = self.app.assets.scaled_image("champion", self.champ_id, self.app.avatar_size) \
            if self.champ_id else None
        if img:
            self.avatar.config(image=img, text="")
        else:
            self.avatar.config(image="", text="+" if not self.champ_id else self.champ_id[:2])
        self.avatar.image = img
        self.name_label.config(text=self.champ_name()[:12] if self.champ_id else "Chọn tướng",
                               fg=FG if self.champ_id else MUTED)

    def refresh_images(self):
        self.refresh_avatar()
        for slot in self.slots:
            slot.refresh_image()
        self.update_level(self.level)  # dữ liệu kỹ năng có thể vừa tải xong

    # ---------- điểm hồi ----------
    def summoner_haste(self, extra=None):
        extra = self.haste.get() if extra is None else extra
        return self.item_haste["summ"] + extra

    def ability_haste_for(self, letter, extra=None):
        """Tổng điểm hồi cho một kỹ năng: trang bị + (hồi chiêu cuối cho R / hồi kỹ năng
        thường cho Q W E) + phần cộng thêm chọn tay."""
        extra = self.ability_haste.get() if extra is None else extra
        bonus = self.item_haste["ult"] if letter == "R" else self.item_haste["basic"]
        return self.item_haste["ah"] + bonus + extra

    def add_auto_lines(self, menu, lines, hint_kind):
        for line in lines:
            menu.add_command(label=line, state="disabled")
        for tree in sorted(self.rune_trees):
            kind, hint = RUNE_TREE_HINTS.get(tree, (None, None))
            if kind == hint_kind:
                menu.add_command(label=f"💡 {hint}", state="disabled")
        menu.add_separator()

    def haste_menu(self, parent):
        menu = make_menu(parent)
        auto = self.item_haste["summ"]
        self.add_auto_lines(menu, [f"Từ trang bị (tự động): +{auto}"] if auto else [], "summ")
        menu.add_command(label="Cộng thêm (ngọc...):", state="disabled")
        for value in self.app.cfg["haste_options"]:
            menu.add_radiobutton(label=HASTE_LABELS.get(value, str(value)), value=value,
                                 variable=self.haste, command=self.render_hastes,
                                 selectcolor=ACCENT)
        return menu

    def show_avatar_menu(self, event):
        menu = make_menu(self.app.root)
        menu.add_command(label="Chọn tướng...", command=lambda: self.app.open_picker(self))
        menu.add_separator()
        menu.add_cascade(label=f"Điểm hồi phép bổ trợ ({self.summoner_haste()})",
                         menu=self.haste_menu(menu))
        menu.add_cascade(label=f"Điểm hồi kỹ năng ({self.item_haste['ah'] + self.ability_haste.get()})",
                         menu=self.ability_haste_menu(menu))
        self.app.popup(menu, event)

    def ability_haste_menu(self, parent):
        menu = make_menu(parent)
        item = self.item_haste
        lines = [f"Từ trang bị (tự động): +{item['ah']}"] if item["ah"] else []
        if item["ult"]:
            lines.append(f"    + {item['ult']} hồi chiêu cuối (chỉ R)")
        if item["basic"]:
            lines.append(f"    + {item['basic']} hồi kỹ năng thường (Q W E)")
        self.add_auto_lines(menu, lines, "ah")
        menu.add_command(label="Cộng thêm (ngọc, mảnh chỉ số...):", state="disabled")
        for value in self.app.cfg["ability_haste_options"]:
            cds = [f"{s.letter} {fmt_time(s.cooldown(extra=value))}"
                   for s in self.ability_slots if s.data()]
            label = f"+{value}   -   " + "  ·  ".join(cds) if cds else f"+{value}"
            menu.add_radiobutton(label=label, value=value, variable=self.ability_haste,
                                 command=self.render_hastes, selectcolor=ACCENT)
        return menu

    def render_hastes(self):
        value = self.summoner_haste()
        self.haste_label.config(text=f"⚡ {value}", fg=ACCENT if value else MUTED)
        value = self.item_haste["ah"] + self.ability_haste.get()
        self.ah_label.config(text=f"◆ {value}", fg=ACCENT if value else MUTED)
        for slot in self.ability_slots:
            slot.render()

    # ---------- dữ liệu trận ----------
    def update_items(self, items):
        """Cộng điểm hồi từ trang bị địch đang có (thông tin trên bảng Tab)."""
        total = dict(NO_HASTE)
        for item in items:
            for kind, value in self.app.assets.item_haste.get(str(item.get("itemID")), {}).items():
                total[kind] += value
        if total != self.item_haste:
            self.item_haste = total
            self.render_hastes()

    def update_runes(self, runes):
        runes = runes or {}
        self.rune_trees = {(runes.get(k) or {}).get("id")
                           for k in ("primaryRuneTree", "secondaryRuneTree")} - {None}

    def update_level(self, level):
        self.level = level
        for slot in self.ability_slots:
            slot.update_level(level)

    def update_api_spells(self, keys):
        """API báo phép đổi giữa trận (vd TP -> TP+): đổi theo, giữ nguyên đếm ngược."""
        if self.api_spells is not None and keys != self.api_spells:
            for slot, old, new in zip(self.spell_slots, self.api_spells, keys):
                if new and new != old and slot.key == old:
                    slot.set_key(new, keep_timer=True)
        self.api_spells = keys

    def reset_timers(self):
        for slot in self.slots:
            slot.reset()


class ChampionPicker:
    """Bảng chọn tướng: tạo một lần, vẽ trên một Canvas, chỉ ẩn / hiện khi dùng."""
    COLS = 8
    CELL_W = 52
    CELL_H = 64

    def __init__(self, app):
        self.app = app
        self.row = None
        self.return_focus = None  # cửa sổ (game) đang có focus trước khi mở bảng
        self.cells = {}  # cid -> (khóa tìm kiếm, item ảnh, item tên)
        self.sorted_cids = []
        self.order = []  # cid theo thứ tự đang hiển thị

        top = self.top = tk.Toplevel(app.root)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=HEADER_BG, highlightthickness=1, highlightbackground="#2d3340")

        bar = tk.Frame(top, bg=HEADER_BG)
        bar.pack(fill="x", padx=6, pady=6)
        self.role_label = tk.Label(bar, font=("Segoe UI", 9, "bold"), bg=HEADER_BG, fg=ACCENT)
        self.role_label.pack(side="left")
        self.search = tk.StringVar()
        self.entry = tk.Entry(bar, textvariable=self.search, font=("Segoe UI", 10), bg=ROW_BG,
                              fg=FG, insertbackground=FG, relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, padx=6, ipady=3)
        close = tk.Label(bar, text="✕", font=("Segoe UI", 10), bg=HEADER_BG, fg=MUTED,
                         cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.hide())

        self.canvas = tk.Canvas(top, bg=HEADER_BG, highlightthickness=0, cursor="hand2",
                                width=self.COLS * self.CELL_W, height=6 * self.CELL_H)
        self.canvas.pack(padx=6, pady=(0, 6))
        self.hover = self.canvas.create_rectangle(0, 0, 0, 0, outline=ACCENT, width=2,
                                                  state="hidden")
        self.empty = self.canvas.create_text(
            self.COLS * self.CELL_W / 2, 60, fill=MUTED, font=("Segoe UI", 9), justify="center",
            text="Đang tải danh sách tướng...\nCần kết nối mạng lần đầu.")

        self.search.trace_add("write", lambda *a: self.apply_filter())
        self.entry.bind("<Return>", lambda e: self.order and self.pick(self.order[0]))
        self.entry.bind("<Escape>", lambda e: self.hide())
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", lambda e: self.canvas.itemconfig(self.hover, state="hidden"))
        top.bind("<MouseWheel>", self.on_wheel)
        # click ra ngoài (cửa sổ chính, game, app khác) -> mất focus -> đóng
        top.bind("<FocusOut>", lambda e: top.after(50, self.hide_if_unfocused))

    def sync(self):
        """Thêm tướng mới / ảnh vừa tải xong vào canvas."""
        for cid, name in self.app.assets.champions.items():
            img = self.app.assets.champion_image(cid)
            if cid in self.cells:
                _, pic, _ = self.cells[cid]
                if img and not self.canvas.itemcget(pic, "image"):
                    self.canvas.itemconfig(pic, image=img)
                continue
            pic = self.canvas.create_image(0, 0, anchor="n", image=img or "", state="hidden")
            label = self.canvas.create_text(0, 0, anchor="n", text=name[:9], fill=FG,
                                            font=("Segoe UI", 7), state="hidden")
            self.cells[cid] = (normalize(cid) + " " + normalize(name), pic, label)
        self.sorted_cids = sorted(self.cells, key=lambda c: self.app.assets.champions.get(c, c))

    def open(self, row):
        if not self.is_open():
            self.return_focus = self.app.outside_foreground()
        self.row = row
        self.sync()
        self.role_label.config(text=f"{row.role}:")
        self.search.set("")
        self.apply_filter()
        x = row.avatar.winfo_rootx() + row.avatar.winfo_width() + 4
        y = self.app.root.winfo_rooty()
        self.top.update_idletasks()
        x = min(x, self.top.winfo_screenwidth() - self.top.winfo_reqwidth())
        y = min(y, self.top.winfo_screenheight() - self.top.winfo_reqheight())
        self.top.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.top.deiconify()
        self.top.lift()
        self.entry.focus_force()

    def is_open(self):
        return bool(self.top.winfo_viewable())

    def hide(self):
        if not self.is_open():
            return
        self.top.withdraw()
        # chỉ trả focus cho game nếu focus vẫn đang ở app (không giành focus của app khác)
        if foreground_window() in self.app.own_windows() or not foreground_window():
            set_foreground(self.return_focus)

    def hide_if_unfocused(self):
        try:
            focus = self.top.focus_get()
        except KeyError:  # focus đang ở menu popup
            focus = None
        if focus is None or focus.winfo_toplevel() is not self.top:
            self.hide()

    def apply_filter(self):
        query = normalize(self.search.get())
        found = [c for c in self.sorted_cids if query in self.cells[c][0]]
        # tên bắt đầu bằng chữ đang gõ lên trước, để Enter chọn đúng tướng
        found.sort(key=lambda c: not any(w.startswith(query) for w in self.cells[c][0].split()))
        self.order = found
        shown = set(found)
        for cid, (_, pic, label) in self.cells.items():
            if cid not in shown:
                self.canvas.itemconfig(pic, state="hidden")
                self.canvas.itemconfig(label, state="hidden")
        for i, cid in enumerate(found):
            _, pic, label = self.cells[cid]
            x = (i % self.COLS + 0.5) * self.CELL_W
            y = (i // self.COLS) * self.CELL_H + 3
            self.canvas.coords(pic, x, y)
            self.canvas.coords(label, x, y + 45)
            self.canvas.itemconfig(pic, state="normal")
            self.canvas.itemconfig(label, state="normal")
        self.canvas.itemconfig(self.empty, state="hidden" if self.cells else "normal")
        self.canvas.itemconfig(self.hover, state="hidden")
        lines = (len(found) + self.COLS - 1) // self.COLS
        self.canvas.configure(scrollregion=(0, 0, self.COLS * self.CELL_W,
                                            max(lines, 6) * self.CELL_H))
        self.canvas.yview_moveto(0)

    def cell_at(self, event):
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        col, line = int(x // self.CELL_W), int(y // self.CELL_H)
        i = line * self.COLS + col
        if 0 <= col < self.COLS and 0 <= i < len(self.order):
            return i
        return None

    def on_motion(self, event):
        i = self.cell_at(event)
        if i is None:
            self.canvas.itemconfig(self.hover, state="hidden")
            return
        x, y = (i % self.COLS) * self.CELL_W, (i // self.COLS) * self.CELL_H
        self.canvas.coords(self.hover, x + 4, y + 2, x + self.CELL_W - 4, y + 47)
        self.canvas.itemconfig(self.hover, state="normal")
        self.canvas.tag_raise(self.hover)

    def on_click(self, event):
        i = self.cell_at(event)
        if i is not None:
            self.pick(self.order[i])

    def on_wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def pick(self, champ_id):
        self.row.set_champion(champ_id)
        self.hide()


class App:
    def __init__(self, mock_path=None):
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.withdraw()  # chưa hiện: tránh nháy cửa sổ + giành focus của game lúc khởi động
        self.root.title("LOL Spell Timer")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.cfg["opacity"])
        self.root.configure(bg=BG)
        self.root.geometry(f"+{self.cfg['x']}+{self.cfg['y']}")
        self.fonts = {name: tkfont.Font(self.root, family="Segoe UI", weight=weight)
                      for name, (_, weight) in FONT_SPECS.items()}
        self.scale = self.cfg["scale"]
        self.update_fonts()

        self.assets = Assets()
        self.assets_seen = self.assets.changed
        self.game_time = None
        self.game_time_at = 0
        self.signature = None
        self.last_seq = -1
        self.status_hold_until = 0
        self.picker = ChampionPicker(self)
        self.visible = False
        self.in_game = False
        self.missed_polls = 0  # số lần liên tiếp không đọc được API (để biết hết trận)
        self.hidden_by_user = False  # bấm ✕ giữa trận: không tự hiện lại tới trận sau

        self.build_header()
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", padx=3, pady=(0, 3))
        self.rows = [EnemyRow(self, body, role, keys) for role, keys in ROLES]
        self.build_grip()
        self.root.bind("<Control-MouseWheel>", self.on_ctrl_wheel)
        self.tray = self.create_tray()
        if not self.tray:  # không có khay hệ thống: hiện như bình thường
            self.show_window()
        elif not self.cfg["tray_hint_shown"]:  # chưa vào trận: nằm ở khay, vào trận tự hiện
            self.tray.notify("LOL Spell Timer đang chạy",
                             "App nằm ở khay hệ thống, tự hiện khi vào trận. "
                             "Click icon để hiện / ẩn, click phải để thoát.")
            self.cfg["tray_hint_shown"] = True
            save_config(self.cfg)

        self.poller = Poller(mock_path)
        self.poller.start()
        self.root.after(300, self.preload_images)
        self.tick()

    # ---------- tỉ lệ / độ trong suốt ----------
    @property
    def icon_size(self):
        return max(16, round(BASE_ICON * self.scale))

    @property
    def avatar_size(self):
        return max(16, round(BASE_AVATAR * self.scale))

    def update_fonts(self):
        for name, (size, _) in FONT_SPECS.items():
            self.fonts[name].configure(size=max(6, round(size * self.scale)))

    def apply_scale(self, scale):
        scale = round(min(max(scale, SCALE_RANGE[0]), SCALE_RANGE[1]), 2)
        if scale == self.scale:
            return
        self.scale = self.cfg["scale"] = scale
        self.update_fonts()
        for row in self.rows:
            row.resize()
        self.set_status(f"cỡ {round(scale * 100)}%", hold=1.5)

    def apply_opacity(self, value):
        value = round(min(max(value, 0.2), 1.0), 2)
        self.cfg["opacity"] = value
        self.root.attributes("-alpha", value)
        set_no_activate(self.root)  # Tk vừa ghi đè extended style
        self.set_status(f"trong suốt {round(value * 100)}%", hold=1.5)

    def on_ctrl_wheel(self, event):
        self.apply_opacity(self.cfg["opacity"] + (0.05 if event.delta > 0 else -0.05))

    def set_compact(self, compact):
        self.cfg["compact"] = compact
        self.title.config(text="⏱" if compact else "⏱ LOL Spell Timer")
        for row in self.rows:
            row.set_compact(compact)
        self.set_status(self.status.cget("text"))

    def build_grip(self):
        """Góc dưới phải: kéo để phóng to / thu nhỏ cả giao diện."""
        grip = tk.Label(self.root, text="◢", font=("Segoe UI", 10), bg=BG, fg="#c8aa6e",
                        cursor="size_nw_se", padx=0, pady=0)
        grip.place(relx=1.0, rely=1.0, anchor="se")
        grip.bind("<ButtonPress-1>", self.grip_start)
        grip.bind("<B1-Motion>", self.grip_move)
        grip.bind("<ButtonRelease-1>", lambda e: save_config(self.cfg))

    def grip_start(self, event):
        self._grip = (event.x_root, self.root.winfo_width(), self.scale)

    def grip_move(self, event):
        x0, width, scale0 = self._grip
        target = scale0 * (width + event.x_root - x0) / width
        self.apply_scale(round(target * 20) / 20)  # bước 5%

    def show_settings(self, event):
        menu = make_menu(self.root)
        opacity = make_menu(menu)
        self._opacity_var = tk.DoubleVar(value=self.cfg["opacity"])
        for value in OPACITY_OPTIONS:
            opacity.add_radiobutton(label=f"{round(value * 100)}%", value=value,
                                    variable=self._opacity_var, selectcolor=ACCENT,
                                    command=lambda v=value: self.save_after(self.apply_opacity, v))
        scale = make_menu(menu)
        self._scale_var = tk.DoubleVar(value=self.scale)
        for value in SCALE_OPTIONS:
            scale.add_radiobutton(label=f"{round(value * 100)}%", value=value,
                                  variable=self._scale_var, selectcolor=ACCENT,
                                  command=lambda v=value: self.save_after(self.apply_scale, v))
        menu.add_cascade(label=f"Độ trong suốt ({round(self.cfg['opacity'] * 100)}%)",
                         menu=opacity)
        menu.add_cascade(label=f"Kích thước ({round(self.scale * 100)}%)", menu=scale)
        self._compact_var = tk.BooleanVar(value=self.cfg["compact"])
        menu.add_checkbutton(label="Chế độ gọn (ẩn tên + điểm hồi)", variable=self._compact_var,
                             selectcolor=ACCENT,
                             command=lambda: self.save_after(self.set_compact,
                                                             self._compact_var.get()))
        menu.add_separator()
        menu.add_command(label="Mẹo: Ctrl + lăn chuột = độ trong suốt", state="disabled")
        menu.add_command(label="Mẹo: kéo góc ◢ = kích thước", state="disabled")
        self.popup(menu, event)

    def own_windows(self):
        windows = {window_handle(self.root)}
        if self.picker.is_open():
            windows.add(window_handle(self.picker.top))
        return windows

    def outside_foreground(self):
        """Cửa sổ đang có focus nếu nó không phải của app (thường là game)."""
        hwnd = foreground_window()
        return hwnd if hwnd and hwnd not in self.own_windows() else None

    def popup(self, menu, event):
        """Mở menu chuột phải. Windows yêu cầu cửa sổ sở hữu menu phải có focus thì menu mới
        đóng khi click ra ngoài, nên lấy focus tạm rồi trả lại game khi menu đóng
        (tk_popup trên Windows chờ đến khi menu đóng mới trả về)."""
        previous = self.outside_foreground()
        set_foreground(window_handle(self.root))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        if previous and not self.picker.is_open():
            set_foreground(previous)

    def save_after(self, action, value):
        action(value)
        save_config(self.cfg)

    # ---------- UI ----------
    def build_header(self):
        header = tk.Frame(self.root, bg=HEADER_BG)
        header.pack(fill="x")
        self.title = tk.Label(header, font=self.fonts["title"], bg=HEADER_BG, fg=FG,
                              text="⏱" if self.cfg["compact"] else "⏱ LOL Spell Timer")
        self.title.pack(side="left", padx=6, pady=3)
        self.status = tk.Label(header, text="", font=self.fonts["text"], bg=HEADER_BG, fg=MUTED)
        self.status.pack(side="left", padx=4)

        close = tk.Label(header, text="✕", font=self.fonts["title"], bg=HEADER_BG, fg=MUTED,
                         cursor="hand2", padx=6)
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.close_button())
        settings = tk.Label(header, text="⚙", font=self.fonts["title"], bg=HEADER_BG, fg=MUTED,
                            cursor="hand2", padx=2)
        settings.pack(side="right")
        settings.bind("<Button-1>", self.show_settings)
        copy = tk.Label(header, text="Copy", font=self.fonts["bold"], bg=HEADER_BG,
                        fg=ACCENT, cursor="hand2", padx=4)
        copy.pack(side="right")
        copy.bind("<Button-1>", lambda e: self.copy_timers())

        for w in (header, self.title, self.status):
            w.bind("<ButtonPress-1>", self.drag_start)
            w.bind("<B1-Motion>", self.drag_move)

    def drag_start(self, event):
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag_move(self, event):
        dx, dy = self._drag
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def open_picker(self, row):
        self.picker.open(row)

    def preload_images(self, pending=None):
        """Nạp sẵn ảnh tướng từng ít một lúc rảnh, để mở bảng chọn tướng không bị khựng."""
        if pending is None:
            pending = list(self.assets.champions)
        for cid in pending[:6]:
            self.assets.champion_image(cid)
        if pending[6:]:
            self.root.after(15, self.preload_images, pending[6:])
        else:
            self.picker.sync()

    def set_status(self, text, hold=0):
        if hold:
            self.status_hold_until = time.monotonic() + hold
        elif time.monotonic() < self.status_hold_until:
            return
        if self.status.cget("text") != text:
            self.status.config(text=text)

    def ingame_status(self):
        clock = fmt_time(self.estimated_game_time() or 0)
        return clock if self.cfg["compact"] else f"trong trận {clock}"

    def spell_cd(self, key, level=None):
        override = self.cfg["cd_override"].get(key)
        if override:
            return override
        if key == "teleport_unleashed":
            hi, lo = UNLEASHED_TP_CD
            level = min(max(level or 14, 1), 18)  # chưa biết level: TP+ mở ở phút 14, ~level 13-14
            return hi - (hi - lo) * (level - 1) / 17
        ddragon_id, _, fallback = SPELLS[key]
        return self.assets.spell_cd.get(ddragon_id) or fallback

    # ---------- dữ liệu trận ----------
    def estimated_game_time(self):
        if self.game_time is None:
            return None
        return self.game_time + (time.monotonic() - self.game_time_at)

    def apply_game_data(self, data, fetched_at):
        self.update_game_presence(data is not None)
        if data is None:
            self.game_time = None
            self.set_status("chưa vào trận" if self.signature is None else "mất kết nối")
            return

        players = data.get("allPlayers", [])
        me = data.get("activePlayer", {})
        my_ids = {me.get("riotId"), me.get("summonerName")} - {None, ""}
        my_team = next((p.get("team") for p in players
                        if {p.get("riotId"), p.get("summonerName")} & my_ids), "ORDER")
        enemies = [p for p in players if p.get("team") != my_team][:len(self.rows)]
        if len(enemies) == len(self.rows) and \
                sorted(API_ROLE_ORDER.get(p.get("position"), -1) for p in enemies) == [0, 1, 2, 3, 4]:
            enemies.sort(key=lambda p: API_ROLE_ORDER[p["position"]])

        def pid(p):
            return p.get("riotId") or p.get("summonerName")

        signature = tuple((pid(p), p.get("championName")) for p in enemies)
        if enemies and signature != self.signature:
            # trận mới: điền tướng / phép, giữ nguyên nếu người dùng đã chọn tay giữa trận
            self.signature = signature
            for row, p in zip(self.rows, enemies):
                row.player_id = pid(p)
                row.item_haste = dict(NO_HASTE)
                row.haste.set(0)
                row.ability_haste.set(0)
                row.level = None
                row.api_spells = None
                row.reset_timers()
                row.champ_id = None  # dựng lại ô kỹ năng theo tướng mới
                row.set_champion(self.assets.find_champion(p))
                row.set_spells([key or default for key, default in
                                 zip(api_spell_keys(p), ROLES[self.rows.index(row)][1])])
                row.render_hastes()

        by_id = {pid(p): p for p in enemies}
        for row in self.rows:
            p = by_id.get(row.player_id)
            if p:
                row.update_items(p.get("items", []))
                row.update_runes(p.get("runes"))
                row.update_level(p.get("level"))
                row.update_api_spells(api_spell_keys(p))

        game_time = data.get("gameData", {}).get("gameTime")
        if game_time is not None:
            self.game_time = game_time
            self.game_time_at = fetched_at
        self.set_status(self.ingame_status())

    def tick(self):
        if self.handle_tray_events():  # người dùng chọn Thoát: cửa sổ đã bị hủy
            return
        with self.poller.lock:
            seq, latest = self.poller.seq, self.poller.latest
        if seq != self.last_seq and latest is not None:
            self.last_seq = seq
            self.apply_game_data(*latest)
        elif self.game_time is not None:
            self.set_status(self.ingame_status())

        if self.assets.changed != self.assets_seen:  # có ảnh mới tải về
            self.assets_seen = self.assets.changed
            for row in self.rows:
                row.refresh_images()
            if len(self.picker.cells) < len(self.assets.champions):
                self.root.after(300, self.preload_images)  # danh sách tướng vừa tải xong

        for row in self.rows:
            for slot in row.slots:
                slot.render()
        self.root.after(200, self.tick)

    # ---------- hành động ----------
    def copy_timers(self):
        parts = []
        for row in self.rows:
            for slot in row.slots:
                left = slot.remaining()
                if not left:
                    continue
                when = (fmt_time(slot.ready_game_time) if slot.ready_game_time is not None
                        else f"còn {fmt_time(left)}")
                parts.append(f"{row.champ_name()} {slot.name} {when}")
        if not parts:
            self.set_status("không có phép nào đang hồi", hold=2)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(" | ".join(parts))
        self.set_status("đã copy, Ctrl+V vào chat", hold=2)

    # ---------- khay hệ thống / tự hiện theo trận ----------
    def create_tray(self):
        if not user32:
            return None
        try:
            return TrayIcon("LOL Spell Timer", ICON_PATH, self.tray_menu_items).start()
        except Exception as e:
            print("Không tạo được icon khay hệ thống:", e)
            return None

    def tray_menu_items(self):  # gọi từ luồng của khay, chỉ đọc giá trị
        return [
            (1, "Ẩn cửa sổ" if self.visible else "Hiện cửa sổ", False),
            (2, "Tự hiện khi vào trận, tự ẩn khi hết trận", self.cfg["auto_show"]),
            (None, None, False),
            (3, "Thoát LOL Spell Timer", False),
        ]

    def handle_tray_events(self):
        """Xử lý thao tác trên icon khay; trả về True nếu app vừa thoát."""
        while self.tray:
            try:
                event = self.tray.events.get_nowait()
            except queue.Empty:
                return False
            if event in ("toggle", 1):
                if self.visible:
                    self.hide_window(by_user=True)
                else:
                    self.show_window()
            elif event == 2:
                self.cfg["auto_show"] = not self.cfg["auto_show"]
                save_config(self.cfg)
            elif event == 3:
                self.quit()
                return True
        return False

    def close_button(self):
        if self.tray:
            self.hide_window(by_user=True)
        else:
            self.quit()

    def show_window(self):
        if self.visible:
            return
        previous = self.outside_foreground()  # thường là game
        self.root.deiconify()
        self.root.geometry(f"+{self.cfg['x']}+{self.cfg['y']}")
        self.root.attributes("-topmost", True)
        set_no_activate(self.root)
        set_foreground(previous)  # hiện lên nhưng không lấy focus của game
        self.visible = True
        self.hidden_by_user = False

    def hide_window(self, by_user=False):
        if self.visible and self.root.winfo_viewable():  # nhớ vị trí để hiện lại đúng chỗ
            self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        self.picker.hide()
        self.root.withdraw()
        self.visible = False
        if by_user and self.in_game:
            self.hidden_by_user = True

    def update_game_presence(self, has_data):
        """Vào trận -> tự hiện; hết trận (mất API ~6 giây liên tục) -> tự ẩn xuống khay."""
        if has_data:
            self.missed_polls = 0
            if not self.in_game:
                self.in_game = True
                self.hidden_by_user = False
            if self.tray and self.cfg["auto_show"] and not self.visible \
                    and not self.hidden_by_user:
                self.show_window()
        else:
            self.missed_polls += 1
            if self.in_game and self.missed_polls >= 3:
                self.in_game = False
                self.hidden_by_user = False
                if self.tray and self.cfg["auto_show"] and self.visible:
                    self.hide_window()

    def quit(self):
        if self.visible and self.root.winfo_viewable():
            self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        save_config(self.cfg)
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # chữ nét trên màn hình scale >100%
    except Exception:
        pass
    mock = None
    if "--mock" in sys.argv:
        mock = sys.argv[sys.argv.index("--mock") + 1]
    App(mock).run()


if __name__ == "__main__":
    main()
