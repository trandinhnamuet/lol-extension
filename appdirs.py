"""Thư mục của app. Người dùng chỉ cần thấy `LOL Spell Timer.exe`: mọi tệp phụ (cấu hình, ảnh tải về, nhật ký,
ảnh chẩn đoán) nằm trong thư mục `data` cạnh exe. Chạy từ mã nguồn thì dùng thư mục dự án như trước.

    APP_DIR  : thư mục chứa exe / spell_timer.py
    DATA_DIR : nơi ghi mọi tệp phụ (APP_DIR/data khi đã đóng gói)
"""
import os
import shutil
import sys

FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else sys.argv[0]))
DATA_DIR = os.path.join(APP_DIR, "data") if FROZEN else APP_DIR
LEGACY = ("config.json", "cache", "update.log", "auto_flash.log", "minimap_snapshot.png", "debug_frames")


def ensure():
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


def migrate():
    """Bản cũ (≤ 1.3.x) để các tệp này ngay cạnh exe: chuyển vào data/ (không ghi đè tệp đã có)."""
    if not FROZEN:
        return 0
    ensure()
    moved = 0
    for name in LEGACY:
        src, dst = os.path.join(APP_DIR, name), os.path.join(DATA_DIR, name)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.move(src, dst)
                moved += 1
            except OSError:
                pass
    return moved


def resource(*parts):
    """Tệp đóng kèm: trong exe nằm ở thư mục giải nén tạm (sys._MEIPASS), khi chạy mã nguồn nằm cạnh mã."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def path(*parts):
    return os.path.join(ensure(), *parts)
