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
IGNITE_RANGE = 600  # đơn vị bản đồ: tầm Thiêu Đốt; kẻ thi triển phải cách nạn nhân (đồng minh) không quá chừng này
IGNITE_SLACK = 1.3  # nới tầm cho sai số vị trí minimap (±2 px) và di chuyển trong 0,5 s
TARGETED = {"ignite": IGNITE_RANGE}  # phép nhắm mục tiêu: quy kết bằng tầm, không bằng cú nhảy
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
        models = dict(flash_listener.DEFAULT_MODELS)
        if not self.cfg.get("auto_ignite", True):
            models.pop("ignite", None)
        self.listener = flash_listener.FlashListener(
            self._on_event, threshold=float(self.cfg.get("auto_flash_threshold", 0.95)), models=models,
            thresholds={"ignite": float(self.cfg.get("auto_ignite_threshold", 0.95))})
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
        allies = tuple(getattr(self.app, "ally_champ_ids", ()))
        enemy_ids = tuple(row.champ_id for row in self.app.rows)
        ids = enemy_ids + ("|",) + allies
        if ids == self.enemy_ids and not force:
            return
        self.enemy_ids = ids
        from spell_timer import CACHE_DIR
        paths = {cid: os.path.join(CACHE_DIR, "champion", cid + ".png") for cid in enemy_ids if cid}
        self.tracker.set_enemies(paths)
        self.tracker.set_allies({cid: os.path.join(CACHE_DIR, "champion", cid + ".png") for cid in allies if cid})
        self.log(f"đội hình: {list(paths)} | đồng minh: {list(allies)}")

    # ---------- sự kiện ----------
    def _on_event(self, t, p, spell="flash"):  # luồng nghe
        with self.lock:
            self.events.append((t, p, spell))

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
        for t, p, spell in ready:
            if spell in TARGETED:
                self.decide_targeted(t, p, spell)
            else:
                self.decide(t, p)
        if self.strip and now >= self.strip_hide_at:
            self.hide_strip()

    def flash_slot(self, row, key="flash"):
        for slot in row.spell_slots:
            if slot.key == key:
                return slot
        return None

    def decide_targeted(self, t, p, spell):
        """Phép nhắm mục tiêu (Thiêu Đốt): kẻ thi triển là địch mang phép, đang cách một đồng minh không quá
        tầm phép quanh mốc tiếng. Một ứng viên và không có đồng minh nào cũng mang phép trong tầm -> tự bấm;
        còn lại hỏi (tiếng của đồng minh và của địch giống nhau)."""
        if self.app.game_time is None:
            self.log(f"tiếng {spell} p={p:.2f} nhưng không trong trận, bỏ qua")
            return
        tracker_ok = self.tracker is not None and self.tracker.status == "đang theo dõi" and self.tracker.frames > 10
        carriers = [row for row in self.app.rows if row.champ_id and self.flash_slot(row, spell)
                    and not self.flash_slot(row, spell).remaining()]
        if not carriers:
            self.log(f"tiếng {spell} p={p:.2f} -> không địch nào mang {spell} còn phép -> bỏ qua")
            return
        if not tracker_ok:
            self.show_strip(carriers, p, spell)
            self.log(f"tiếng {spell} p={p:.2f} -> minimap không chạy -> HỎI {[r.champ_id for r in carriers]}")
            return
        radius = self.tracker.units_to_px(TARGETED[spell]) * IGNITE_SLACK
        t0, t1 = t - 0.3, t + 0.5
        near = []
        for row in carriers:
            pos = self.tracker.position(row.champ_id, t0, t1)
            if pos is None:
                continue
            n_ally = self.tracker.allies_near(pos[0], pos[1], radius, t0, t1)
            if n_ally:
                near.append((row, pos, n_ally))
        ally_carriers = [c for c in getattr(self.app, "ally_ignite_ids", ()) if c]
        ambiguous = False
        if near and ally_carriers:  # đồng minh mang cùng phép đứng trong tầm ứng viên: có thể chính đồng minh vừa dùng
            for row, pos, _ in near:
                for c in ally_carriers:
                    ap_ = self.tracker.position(c, t0, t1, ally=True)
                    if ap_ is not None and ((ap_[0] - pos[0]) ** 2 + (ap_[1] - pos[1]) ** 2) ** 0.5 <= radius:
                        ambiguous = True
        info = [f"{r.champ_id}@({pos[0]:.0f},{pos[1]:.0f}) đồng minh gần:{n}" for r, pos, n in near]
        note = " (đồng minh cũng mang)" if ambiguous else ""
        if len(near) == 1 and not ambiguous:
            self.auto_start(near[0][0], spell)
            self.log(f"tiếng {spell} p={p:.2f} -> trong tầm {info} -> TỰ BẤM {near[0][0].champ_id}")
        elif near:
            self.show_strip([r for r, _, _ in near], p, spell)
            self.log(f"tiếng {spell} p={p:.2f} -> trong tầm {info}{note} -> HỎI")
        elif self.cfg.get("auto_flash_ask_unknown", True):
            self.show_strip(carriers, p, spell)
            self.log(f"tiếng {spell} p={p:.2f} -> không ứng viên trong tầm -> HỎI {[r.champ_id for r in carriers]}")
        else:
            self.log(f"tiếng {spell} p={p:.2f} -> không ứng viên trong tầm -> bỏ qua")

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

    def auto_start(self, row, spell="flash"):
        slot = self.flash_slot(row, spell)
        if slot and not slot.remaining():
            slot.start()
            slot.auto_label_until = time.monotonic() + AUTO_LABEL_SECONDS
            slot._last_render = None
            self.app.set_status(f"tự bấm {slot.name} {row.champ_name()}", hold=3)

    # ---------- dải hỏi ----------
    def show_strip(self, rows, p, spell="flash"):
        from spell_timer import ACCENT, BG, FG, MUTED, ROW_BG, SPELLS
        self.hide_strip()
        if not rows:
            return
        app = self.app
        self.strip_spell = spell
        strip = tk.Frame(app.root, bg=ROW_BG)
        strip.pack(fill="x", padx=3, pady=(0, 3))
        tk.Label(strip, text=f"Nghe thấy {SPELLS[spell][1]} ({p:.0%}) — ai?", font=app.fonts["bold"],
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
        spell = getattr(self, "strip_spell", "flash")
        self.auto_start(row, spell)
        self.log(f"người dùng chọn {row.champ_id} ({spell})")
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
