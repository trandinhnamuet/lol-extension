"""Tự cập nhật LOL Spell Timer.exe từ GitHub Releases (repo phát hành công khai, tách khỏi repo mã nguồn).

Luồng:
  1. check(): đọc version.json của bản phát hành mới nhất
     (https://github.com/<REPO>/releases/latest/download/version.json, do release/publish.py tạo khi đăng bản).
     Không có mạng / GitHub lỗi -> None: dùng bình thường, không báo gì.
  2. download(): tải exe mới về <exe>.new (qua .part), kiểm cỡ và SHA-256.
  3. install(): Windows không cho ghi đè exe đang chạy nhưng cho đổi tên: <exe> -> <exe>.old,
     <exe>.new -> <exe>. Lỗi giữa chừng thì đổi tên ngược lại (không bao giờ mất exe).
  4. restart(): chạy lại exe (đã là bản mới), bản cũ thoát. Lần mở sau cleanup_old() xoá <exe>.old.
Chạy từ mã nguồn (không đóng gói) chỉ kiểm tra và báo, không thay file.

Bảo mật: link tải phải thuộc https://github.com/<REPO>/releases/ và file phải khớp SHA-256 trong
version.json. Biến môi trường kiểm thử (LOLSPELLTIMER_UPDATE_URL) chỉ có hiệu lực khi chạy từ mã nguồn
hoặc khi cạnh exe có file cờ lolspelltimer-test.flag.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from version import APP_VERSION

REPO = "trandinhnamuet/lol-spell-timer-releases"
MANIFEST_URL = f"https://github.com/{REPO}/releases/latest/download/version.json"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
TRUSTED_PREFIX = f"https://github.com/{REPO}/releases/"
TEST_FLAG = "lolspelltimer-test.flag"
CHECK_EVERY = 6 * 3600  # giây: kiểm tra lại khi app mở lâu
TIMEOUT = 10


class UpdateError(Exception):
    pass


def log(msg):
    """Nhật ký cập nhật (update.log cạnh exe / file chạy); không bao giờ làm hỏng luồng chính."""
    try:
        import appdirs
        with open(appdirs.path("update.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} v{APP_VERSION} {msg}\n")
    except Exception:
        pass


def vtuple(v):
    """"1.2.0" / "v1.2" -> (1, 2, 0) / (1, 2); không đọc được -> (0,)."""
    nums = re.findall(r"\d+", str(v or ""))
    return tuple(int(n) for n in nums) or (0,)


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def exe_path():
    return os.path.abspath(sys.executable)


def test_overrides_allowed():
    if not is_frozen():
        return True
    return os.path.exists(os.path.join(os.path.dirname(exe_path()), TEST_FLAG))


def manifest_url():
    return (os.environ.get("LOLSPELLTIMER_UPDATE_URL") if test_overrides_allowed() else None) or MANIFEST_URL


def safe_page(url):
    """Chỉ mở trang https://github.com/... (tránh webbrowser.open chạy một đường dẫn bất kỳ)."""
    return url if isinstance(url, str) and url.startswith("https://github.com/") else RELEASES_PAGE


def _open(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": f"LOLSpellTimer/{APP_VERSION}"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_manifest(url=None, timeout=TIMEOUT):
    with _open(url or manifest_url(), timeout) as r:
        m = json.loads(r.read(1 << 20).decode("utf-8"))
    asset = m.get("asset") if isinstance(m, dict) else None
    if not isinstance(asset, dict) or "version" not in m or not asset.get("url") or not asset.get("sha256"):
        raise UpdateError("version.json không đúng dạng")
    return m


def plain(md):
    """Ghi chú markdown -> chữ thường để hiện trong app."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", md.strip())
    s = s.replace("`", "")
    s = re.sub(r"(?m)^#+\s*", "", s)
    return re.sub(r"(?m)^- ", "• ", s)


class UpdateInfo:
    """state = "current" | "available"."""

    def __init__(self, manifest, current=APP_VERSION):
        self.manifest = manifest
        self.current = str(current)
        self.latest = str(manifest["version"])
        self.state = "available" if vtuple(self.current) < vtuple(self.latest) else "current"
        self.asset = manifest["asset"]
        self.page = safe_page(manifest.get("page"))

    def notes_since(self):
        """Ghi chú của mọi bản mới hơn bản đang dùng (mới nhất trước)."""
        notes = self.manifest.get("notes") or {}
        lo, hi = vtuple(self.current), vtuple(self.latest)
        vs = sorted((v for v in notes if lo < vtuple(v) <= hi), key=vtuple, reverse=True)
        return "\n\n".join(f"v{v}\n{plain(notes[v])}" for v in vs) or "(không có ghi chú)"


def check(current=APP_VERSION, url=None):
    """UpdateInfo, hoặc None khi không kiểm tra được: khi đó dùng bình thường."""
    try:
        return UpdateInfo(fetch_manifest(url), current)
    except Exception as e:  # noqa: BLE001
        globals()["log"](f"không kiểm tra được bản mới ({type(e).__name__}: {e}); dùng bình thường")
        return None


def _check_url(url):
    if not test_overrides_allowed() and not str(url).startswith(TRUSTED_PREFIX):
        raise UpdateError("link tải không thuộc trang phát hành chính thức: bỏ qua")


def _check_writable(d):
    probe = os.path.join(d, f".lolspelltimer_write_test_{os.getpid()}")
    try:
        with open(probe, "wb") as f:
            f.write(b"x")
        os.remove(probe)
    except OSError as e:
        raise UpdateError(f"không ghi được vào thư mục {d} ({e.strerror or e}). Hãy tải bản mới tại {RELEASES_PAGE}")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def download(info, dst=None, progress=None, cancel=None, chunk=1 << 18):
    """Tải exe mới về dst (mặc định <exe>.new), kiểm cỡ + SHA-256. progress(đã tải, tổng).
    cancel() trả True thì dừng. Trả đường dẫn file."""
    a = info.asset
    _check_url(a["url"])
    dst = dst or exe_path() + ".new"
    d = os.path.dirname(dst)
    _check_writable(d)
    size = int(a.get("size") or 0)
    if size and shutil.disk_usage(d).free < size * 1.2 + (50 << 20):
        raise UpdateError(f"ổ đĩa không đủ chỗ trống (cần ~{size / 1e6:.0f} MB)")
    part = dst + ".part"
    h = hashlib.sha256()
    done = 0
    try:
        with _open(a["url"], timeout=30) as r, open(part, "wb") as f:
            total = size or int(r.headers.get("Content-Length") or 0)
            while True:
                if cancel and cancel():
                    raise UpdateError("đã huỷ")
                b = r.read(chunk)
                if not b:
                    break
                f.write(b)
                h.update(b)
                done += len(b)
                if progress:
                    progress(done, total)
        if size and done != size:
            raise UpdateError(f"tải thiếu ({done} / {size} byte)")
        if h.hexdigest().lower() != str(a["sha256"]).lower():
            raise UpdateError("file tải về không khớp mã SHA-256 (hỏng hoặc bị thay đổi)")
        os.replace(part, dst)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return dst


def install(new, sha256, exe=None):
    """Thay exe bằng bản .new (đổi tên được cả exe đang chạy). Lỗi thì hoàn tác."""
    exe = exe or exe_path()
    if sha256_file(new).lower() != str(sha256).lower():  # kiểm lại ngay trước khi thay (chống tráo .new)
        raise UpdateError("file đã bị thay đổi sau khi tải: không cài")
    old = exe + ".old"
    if os.path.exists(old):
        try:
            os.remove(old)
        except OSError:  # .old của lần trước còn đang chạy: dùng tên khác
            old = f"{exe}.old{int(time.time() * 1000)}"
    os.replace(exe, old)
    try:
        os.replace(new, exe)
    except BaseException:
        os.replace(old, exe)
        raise


def cleanup_old(exe=None):
    """Xoá <exe>.old* / .new / .part còn sót của lần cập nhật trước."""
    if not is_frozen() and exe is None:
        return 0
    exe = os.path.abspath(exe or sys.executable)
    n = 0
    for p in glob.glob(exe + ".old*") + glob.glob(exe + ".new*"):
        try:
            os.remove(p)
            n += 1
        except OSError:
            pass  # còn đang chạy: lần sau xoá
    return n


def restart(args=(), exe=None):
    """Chạy lại exe (bản mới). PYINSTALLER_RESET_ENVIRONMENT: bản mới tự giải nén riêng, không dùng lại
    thư mục tạm của bản cũ (thư mục đó bị xoá khi bản cũ thoát)."""
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for k in list(env):
        if k.startswith("_PYI_") or k == "_MEIPASS2":
            env.pop(k, None)
    exe = os.path.abspath(exe or sys.executable)
    return subprocess.Popen([exe] + list(args), env=env, close_fds=True, cwd=os.path.dirname(exe))
