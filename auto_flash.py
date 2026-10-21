"""Tự bắt Flash: nghe tiếng Flash (flash_listener) + xem icon địch nào nhảy trên minimap
(minimap_tracker) -> bấm đếm ngược Flash của đúng hàng trong app, hoặc hỏi người dùng.

Chỉ `poll()` và các hàm UI chạy ở luồng Tk; sự kiện từ luồng nghe được xếp vào hàng đợi.
Mọi quyết định được ghi vào auto_flash.log cạnh app (để đối chiếu với HUD khi thử bằng replay).
"""
import os
import sys
import threading
import time
import tkinter as tk
from collections import deque

APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
LOG_PATH = os.path.join(APP_DIR, "auto_flash.log")
DECIDE_AFTER = 0.5  # giây sau mốc tiếng mới quyết định (chờ minimap ghi được cú nhảy)
ASK_SECONDS = 6  # dải hỏi tự ẩn sau chừng này giây
AUTO_LABEL_SECONDS = 3


class AutoFlash:
    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg
        self.listener = None
        self.tracker = None
        self.events = deque()  # (t, p) từ luồng nghe
        self.pending = []  # chờ đủ DECIDE_AFTER
        self.lock = threading.Lock()
        self.enemy_ids = None
        self.strip = None
        self.strip_hide_at = 0
        self.strip_images = []
        self.log_file = None
        self.enabled = False

    # ---------- bật / tắt ----------
    def set_enabled(self, on):
        self.cfg["auto_flash"] = bool(on)
        if on and not self.enabled:
            self.start()
        elif not on and self.enabled:
            self.stop()

    def start(self):
        import flash_listener
        import minimap_tracker
        self.enabled = True
        self.log_file = open(LOG_PATH, "a", encoding="utf-8")
        self.log("bật")
        self.listener = flash_listener.FlashListener(self._on_event,
                                                     threshold=float(self.cfg.get("auto_flash_threshold", 0.95)))
        self.listener.start()
        rect = self.cfg.get("minimap_rect")
        self.tracker = minimap_tracker.MinimapTracker(rect=tuple(rect) if rect else None)
        self.enemy_ids = None
        self.sync_enemies(force=True)
        self.tracker.start()

    def stop(self):
        self.enabled = False
        if self.listener:
            self.listener.stop()
        if self.tracker:
            self.tracker.stop()
        self.listener = self.tracker = None
        self.hide_strip()
        self.log("tắt")
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    def log(self, msg):
        if not self.log_file:
            return
        gt = self.app.estimated_game_time()
        gts = f"{int(gt) // 60}:{int(gt) % 60:02d}" if gt is not None else "--:--"
        self.log_file.write(f"{time.strftime('%H:%M:%S')} mono={time.monotonic():.2f} game={gts} {msg}\n")
        self.log_file.flush()

    def status(self):
        if not self.enabled:
            return "tắt"
        parts = []
        if self.listener:
            parts.append("nghe: " + self.listener.status)
        if self.tracker:
            parts.append("minimap: " + self.tracker.status)
        return " | ".join(parts)

    # ---------- đội hình ----------
    def sync_enemies(self, force=False):
        """Cập nhật mẫu icon theo tướng của 5 hàng (gọi mỗi lần poll, rẻ khi không đổi)."""
        if not self.tracker:
            return
        ids = tuple(row.champ_id for row in self.app.rows)
        if ids == self.enemy_ids and not force:
            return
        self.enemy_ids = ids
        from spell_timer import CACHE_DIR
        paths = {cid: os.path.join(CACHE_DIR, "champion", cid + ".png") for cid in ids if cid}
        self.tracker.set_enemies(paths)
        self.log(f"đội hình: {list(paths)}")

    # ---------- sự kiện ----------
    def _on_event(self, t, p):  # luồng nghe
        with self.lock:
            self.events.append((t, p))

    def poll(self):
        """Gọi từ App.tick (mỗi 200 ms, luồng Tk)."""
        if not self.enabled:
            return
        self.sync_enemies()
        with self.lock:
            while self.events:
                self.pending.append(self.events.popleft())
        now = time.monotonic()
        if now - getattr(self, "_last_status_log", 0) >= 30:  # trạng thái định kỳ để chẩn đoán
            self._last_status_log = now
            self.log("trạng thái: " + self.status() + (f" ({self.tracker.frames} khung)" if self.tracker else ""))
        ready = [e for e in self.pending if now - e[0] >= DECIDE_AFTER]
        self.pending = [e for e in self.pending if now - e[0] < DECIDE_AFTER]
        for t, p in ready:
            self.decide(t, p)
        if self.strip and now >= self.strip_hide_at:
            self.hide_strip()

    def flash_slot(self, row):
        for slot in row.spell_slots:
            if slot.key == "flash":
                return slot
        return None

    def decide(self, t, p):
        if self.app.game_time is None:
            self.log(f"tiếng p={p:.2f} nhưng không trong trận, bỏ qua")
            return
        rows_by_champ = {row.champ_id: row for row in self.app.rows if row.champ_id}
        tracker_ok = self.tracker is not None and self.tracker.status == "đang theo dõi" and self.tracker.frames > 10
        jumped = self.tracker.who_jumped(t) if tracker_ok else []
        if tracker_ok:  # vết vị trí quanh mốc tiếng, để chẩn đoán vì sao không thấy cú nhảy
            with self.tracker.lock:
                tracks = {c: [(round(tt - t, 2), round(x), round(y), round(sc, 2)) for tt, x, y, sc in h
                              if t - 0.8 <= tt <= t + 0.5] for c, h in self.tracker.history.items()}
            self.log("vết: " + "; ".join(f"{c}={v}" for c, v in tracks.items() if v))
        candidates = [(rows_by_champ[c], px) for c, px in jumped if c in rows_by_champ]
        # bỏ ứng viên mà Flash đang hồi sẵn (đã bấm rồi, hoặc khớp nhiễu)
        candidates = [(row, px) for row, px in candidates
                      if self.flash_slot(row) and not self.flash_slot(row).remaining()]
        names = [f"{row.champ_id}:{px:.0f}px" for row, px in candidates]
        if len(candidates) == 1:
            row = candidates[0][0]
            self.auto_start(row)
            self.log(f"tiếng p={p:.2f} -> nhảy {names} -> TỰ BẤM {row.champ_id}")
            return
        free = [row for row in self.app.rows
                if row.champ_id and self.flash_slot(row) and not self.flash_slot(row).remaining()]
        ask = [row for row, _ in candidates] if candidates else free
        if not tracker_ok or candidates or self.cfg.get("auto_flash_ask_unknown", True):
            self.show_strip(ask, p)
            self.log(f"tiếng p={p:.2f} -> nhảy {names} (minimap {'ok' if tracker_ok else 'không chạy'}) -> HỎI {[r.champ_id for r in ask]}")
        else:
            self.log(f"tiếng p={p:.2f} -> không icon địch nào nhảy -> bỏ qua")

    def auto_start(self, row):
        slot = self.flash_slot(row)
        if slot and not slot.remaining():
            slot.start()
            slot.auto_label_until = time.monotonic() + AUTO_LABEL_SECONDS
            slot._last_render = None
            self.app.set_status(f"tự bấm Flash {row.champ_name()}", hold=3)

    # ---------- dải hỏi ----------
    def show_strip(self, rows, p):
        from spell_timer import ACCENT, BG, FG, MUTED, ROW_BG
        self.hide_strip()
        if not rows:
            return
        app = self.app
        strip = tk.Frame(app.root, bg=ROW_BG)
        strip.pack(fill="x", padx=3, pady=(0, 3))
        tk.Label(strip, text=f"Nghe thấy Flash ({p:.0%}) — ai?", font=app.fonts["bold"],
                 bg=ROW_BG, fg=ACCENT).pack(side="left", padx=(6, 8))
        size = app.avatar_size
        self.strip_images = []
        for row in rows:
            img = app.assets.scaled_image("champion", row.champ_id, size)
            btn = tk.Label(strip, bg="#2a2e37", fg=FG, cursor="hand2", bd=1, relief="solid",
                           text=(row.champ_name() or "?")[:6] if img is None else "")
            if img is not None:
                btn.config(image=img, width=size, height=size)
                self.strip_images.append(img)
            btn.pack(side="left", padx=2, pady=3)
            btn.bind("<Button-1>", lambda e, r=row: self.pick(r))
        tk.Label(strip, text="✕", font=app.fonts["bold"], bg=ROW_BG, fg=MUTED, cursor="hand2",
                 padx=6).pack(side="right")
        strip.winfo_children()[-1].bind("<Button-1>", lambda e: self.hide_strip())
        self.strip = strip
        self.strip_hide_at = time.monotonic() + ASK_SECONDS

    def pick(self, row):
        self.auto_start(row)
        self.log(f"người dùng chọn {row.champ_id}")
        self.hide_strip()

    def hide_strip(self):
        if self.strip:
            self.strip.destroy()
            self.strip = None
            self.strip_images = []

    def snapshot(self):
        path = os.path.join(APP_DIR, "minimap_snapshot.png")
        if self.tracker and self.tracker.snapshot(path):
            self.app.set_status("đã lưu minimap_snapshot.png", hold=3)
        else:
            self.app.set_status("minimap chưa chạy", hold=3)
