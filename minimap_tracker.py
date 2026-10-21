"""Theo dõi vị trí 5 tướng địch trên minimap để biết ai vừa Flash (icon nhảy ~400 đơn vị bản đồ
≈ 7 px trên minimap 1080p trong một khung, còn đi bộ chỉ ~0,2 px/khung).

Cách làm (mỗi khung, ~20 fps, vùng minimap ~264×270 px):
1. Mặt nạ màu đỏ (viền icon địch là vòng đỏ 2 px, H≈0, S≥120, V≥120) → HoughCircles bán kính
   10–14 px → tâm các icon địch đang hiện. Trụ / ping đỏ bị loại vì lõi đặc đỏ.
2. Với mỗi vòng: cắt đĩa trong, so với chân dung Data Dragon của 5 địch (thu về cùng cỡ, mặt nạ
   tròn, NCC) → điểm từng tướng. Gán danh tính tham lam theo điểm, ưu tiên giữ danh tính của
   vết (track) ở gần vị trí cũ (icon chồng nhau trong giao tranh thì chân dung bị che).
3. Lịch sử vị trí 3 s mỗi tướng. `who_jumped(t)`: dịch ≥ ~5 px trong ≤ 0,25 s quanh mốc tiếng và
   ở lại chỗ mới.

    tracker = MinimapTracker(rect=(x, y, w, h))
    tracker.set_enemies({"Zed": "cache/champion/Zed.png", ...})
    tracker.start();  tracker.who_jumped(t_monotonic) -> [("Zed", px), ...]

rect mặc định: minimap LMHT 1920×1080 tỉ lệ mặc định (x 1656, y 810, 264×270). Màn hình khác:
truyền rect hoặc chỉnh `minimap_rect` trong config.json; `snapshot(path)` lưu ảnh kiểm.
"""
import os
import sys
import threading
import time
from collections import deque

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

DEFAULT_RECT_FRAC = (0.8625, 0.75, 0.1375, 0.25)  # x, y, w, h theo tỉ lệ màn hình 1920×1080
RING_R_FRAC = (0.036, 0.055)  # bán kính vòng icon / cạnh minimap (10–14 px ở 264 px)
MATCH_MIN = 0.35  # NCC chân dung tối thiểu để gán danh tính mới (cùng vị trí cũ thì nới hơn)
HISTORY_SECONDS = 3.0
JUMP_PX_FRAC = 0.019  # bước nhảy tối thiểu / cạnh minimap (~5 px ở 264 px; Flash 400 đơn vị ~ 7 px, đo thật 6-10 px)
JUMP_MAX_FRAC = 0.045  # bước nhảy tối đa (~12 px): xa hơn là mất dấu / nhầm danh tính, không phải Flash
STABLE_BEFORE = 0.3  # giây: trước cú nhảy icon phải đứng yên quanh chỗ cũ (loại nhầm danh tính 1-2 khung)
STABLE_TOL_FRAC = 0.017  # ~4,5 px: tâm vòng Hough rung ±2 px nên "đứng yên" phải nới chừng này
JUMP_MAX_DT = 0.25  # giây: bước nhảy phải xảy ra trong chừng này
WINDOW_BEFORE, WINDOW_AFTER = 0.1, 0.4  # giây quanh mốc tiếng: đo thật cú nhảy đến sau mốc tiếng 0,08-0,31 s
TRACK_DIST = 10  # px: vết cũ cách vòng mới dưới chừng này thì coi là cùng tướng
CORE_RED_MAX = 0.35  # lõi vòng có hơn chừng này điểm đỏ -> trụ / ping, không phải icon
RING_MIN_FRAC = 0.3  # phần vành (r±1,5 px) phải có màu đang tìm
RING_OTHER_MAX = 0.2  # vành không được là màu phe kia


def default_rect():
    try:
        import ctypes
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
    except Exception:
        w, h = 1920, 1080
    fx, fy, fw, fh = DEFAULT_RECT_FRAC
    return int(w * fx), int(h * fy), int(w * fw), int(h * fh)


def circular_template(path, size):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None, None
    h, w = img.shape[:2]
    m = min(h, w)
    img = img[(h - m) // 2:(h - m) // 2 + m, (w - m) // 2:(w - m) // 2 + m]
    img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    mask = np.zeros((size, size), np.uint8)
    cv2.circle(mask, (size // 2, size // 2), size // 2 - 1, 255, -1)
    return img, mask


def red_mask(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return (((h <= 10) | (h >= 170)) & (s >= 120) & (v >= 120)).astype(np.uint8) * 255


def blue_mask(frame):
    """Viền icon đồng minh (xanh dương); icon của chính mình viền sáng hơn, cũng lọt vào đây."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return ((h >= 95) & (h <= 125) & (s >= 110) & (v >= 120)).astype(np.uint8) * 255


def find_rings(frame, r_min, r_max, color="red"):
    """Tâm và bán kính các vòng (icon tướng) trên minimap; color = "red" (địch) | "blue" (đồng minh)."""
    mask = red_mask(frame) if color == "red" else blue_mask(frame)
    circles = cv2.HoughCircles(mask, cv2.HOUGH_GRADIENT, dp=1, minDist=r_min, param1=50, param2=8,
                               minRadius=r_min, maxRadius=r_max)
    out = []
    if circles is None:
        return out
    H, W = mask.shape
    other = blue_mask(frame) if color == "red" else red_mask(frame)
    yy, xx = np.ogrid[:H, :W]
    for x, y, r in circles[0]:
        x, y, r = float(x), float(y), float(r)
        if x - r < 0 or y - r < 0 or x + r >= W or y + r >= H:
            continue
        # vành phải thật sự có màu đang tìm (Hough trên mask dễ "vẽ" vòng qua các mảng màu rời rạc),
        # và không phải vành màu kia (chân dung tím/xanh bên trong icon địch có thể bị coi là xanh)
        ring = ((xx - x) ** 2 + (yy - y) ** 2 <= (r + 1.5) ** 2) & ((xx - x) ** 2 + (yy - y) ** 2 >= (r - 1.5) ** 2)
        if ring.any():
            if (mask[ring] > 0).mean() < RING_MIN_FRAC or (other[ring] > 0).mean() > RING_OTHER_MAX:
                continue
        core = r - 4
        if core >= 3:
            y0, y1, x0, x1 = int(y - core), int(y + core) + 1, int(x - core), int(x + core) + 1
            sub = mask[y0:y1, x0:x1]
            cy_, cx_ = np.ogrid[y0:y1, x0:x1]  # lưới riêng, không ghi đè yy/xx của cả khung
            disc = (cx_ - x) ** 2 + (cy_ - y) ** 2 <= core ** 2
            if disc.any() and (sub[disc] > 0).mean() > CORE_RED_MAX:
                continue  # đặc đỏ: trụ, ping
        out.append((x, y, r))
    return out


class MinimapTracker(threading.Thread):
    def __init__(self, rect=None, fps=20):
        super().__init__(daemon=True)
        self.rect = rect or default_rect()
        self.fps = fps
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.templates = {}  # champ -> {size: (img, mask)}
        self.paths = {}
        self.history = {}  # champ -> deque[(t, x, y, score)]
        self.ally_paths = {}  # đồng minh: chỉ cần vị trí; chân dung (nếu có) để biết ai mang phép gì
        self.ally_history = {}  # champ (hoặc "?n") -> deque[(t, x, y, score)]
        self.track_allies = False
        self.status = "chưa chạy"
        self.frames = 0
        self.last_frame = None
        self.last_rings = []
        self.last_blue = []
        self.blue_positions = deque()
        side = min(self.rect[2], self.rect[3])
        self.r_min, self.r_max = max(6, int(side * RING_R_FRAC[0])), int(side * RING_R_FRAC[1]) + 1

    def set_enemies(self, champ_paths):
        with self.lock:
            self.paths = {c: p for c, p in champ_paths.items() if p and os.path.exists(p)}
            self.templates = {c: {} for c in self.paths}
            self.history = {c: deque() for c in self.paths}

    def set_allies(self, champ_paths):
        """Bật theo dõi vòng xanh. champ_paths: {champ_id: png} của đồng minh (kể cả mình); có thể rỗng."""
        with self.lock:
            self.ally_paths = {c: p for c, p in (champ_paths or {}).items() if p and os.path.exists(p)}
            for c in self.ally_paths:
                self.templates.setdefault(c, {})
            self.ally_history = {c: deque() for c in self.ally_paths}
            self.track_allies = True

    def _template(self, champ, size):
        cache = self.templates.setdefault(champ, {})
        if size not in cache:
            path = self.paths.get(champ) or self.ally_paths.get(champ)
            cache[size] = circular_template(path, size) if path else (None, None)
        return cache[size]

    def _grab(self, sct):
        x, y, w, h = self.rect
        shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    def _identify(self, frame, rings, t, paths=None, history=None):
        """Điểm NCC của từng tướng tại từng vòng, rồi gán tham lam có nhớ vết."""
        with self.lock:
            paths = self.paths if paths is None else paths
            history = self.history if history is None else history
            champs = list(paths)
            last = {c: (h[-1] if h else None) for c, h in history.items()}
        if not champs or not rings:
            return
        scores = np.full((len(rings), len(champs)), -1.0)
        for i, (x, y, r) in enumerate(rings):
            d = int(2 * (r - 2))
            if d < 6:
                continue
            x0, y0 = int(round(x - d / 2)), int(round(y - d / 2))
            crop = frame[y0:y0 + d, x0:x0 + d]
            if crop.shape[0] != d or crop.shape[1] != d:
                continue
            for j, c in enumerate(champs):
                tpl, mask = self._template(c, d)
                if tpl is None:
                    continue
                res = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED, mask=mask)
                v = float(res[0, 0])
                scores[i, j] = v if np.isfinite(v) and -1 <= v <= 1 else -1.0
        # ưu tiên vết: vòng gần vị trí cũ của tướng nào thì cộng điểm cho tướng đó
        bonus = np.zeros_like(scores)
        for j, c in enumerate(champs):
            p = last.get(c)
            if p is None or t - p[0] > 1.0:
                continue
            for i, (x, y, r) in enumerate(rings):
                dist = np.hypot(x - p[1], y - p[2])
                if dist <= TRACK_DIST:
                    bonus[i, j] = 0.4 * (1 - dist / TRACK_DIST)
        total = scores + bonus
        assigned = {}
        used_rings, used_champs = set(), set()
        for _ in range(min(len(rings), len(champs))):
            best = None
            for i in range(len(rings)):
                if i in used_rings:
                    continue
                for j in range(len(champs)):
                    if j in used_champs:
                        continue
                    if best is None or total[i, j] > best[0]:
                        best = (total[i, j], i, j)
            if best is None or best[0] < MATCH_MIN:
                break
            _, i, j = best
            used_rings.add(i)
            used_champs.add(j)
            assigned[champs[j]] = (rings[i][0], rings[i][1], float(scores[i, j]))
        with self.lock:
            for c, (x, y, s) in assigned.items():
                h = history.get(c)
                if h is None:
                    continue
                h.append((t, x, y, s))
                while h and t - h[0][0] > HISTORY_SECONDS:
                    h.popleft()

    def process(self, frame, t):
        rings = find_rings(frame, self.r_min, self.r_max)
        self.last_rings = rings
        self._identify(frame, rings, t)
        if self.track_allies:
            blue = find_rings(frame, self.r_min, self.r_max, "blue")
            # chân dung tím/xanh bên trong icon địch cũng tạo "vòng xanh": bỏ vòng xanh trùng vị trí vòng đỏ
            blue = [b for b in blue if all(np.hypot(b[0] - r[0], b[1] - r[1]) > 6 for r in rings)]
            self.last_blue = blue
            if self.ally_paths:
                self._identify(frame, blue, t, self.ally_paths, self.ally_history)
            with self.lock:  # vị trí mọi vòng xanh, không cần biết ai (cho luật tầm phép nhắm mục tiêu)
                self.blue_positions.append((t, [(x, y) for x, y, r in blue]))
                while self.blue_positions and t - self.blue_positions[0][0] > HISTORY_SECONDS:
                    self.blue_positions.popleft()
        return rings

    def position(self, champ, t0, t1, ally=False):
        """Vị trí (x, y) trung vị của tướng trong [t0, t1], hoặc None."""
        with self.lock:
            h = (self.ally_history if ally else self.history).get(champ, ())
            pts = [(x, y) for t, x, y, s in h if t0 <= t <= t1]
        if not pts:
            return None
        return float(np.median([p[0] for p in pts])), float(np.median([p[1] for p in pts]))

    def allies_near(self, x, y, radius, t0, t1):
        """Số vòng xanh (đồng minh/mình) cách (x, y) <= radius trong [t0, t1] (tính theo khung gần nhất)."""
        with self.lock:
            frames = [pts for t, pts in self.blue_positions if t0 <= t <= t1]
        best = 0
        for pts in frames:
            best = max(best, sum(1 for px, py in pts if np.hypot(px - x, py - y) <= radius))
        return best

    def units_to_px(self, units, map_units=14800):
        """Đơn vị bản đồ -> px minimap (Summoner's Rift ~14800 đơn vị mỗi cạnh)."""
        return units / map_units * min(self.rect[2], self.rect[3])

    def run(self):
        if cv2 is None:
            self.status = "thiếu OpenCV"
            return
        try:
            import mss
        except ImportError:
            self.status = "thiếu mss"
            return
        interval = 1 / self.fps
        try:
            with mss.mss() as sct:
                self.status = "đang theo dõi"
                next_at = time.monotonic()
                while not self.stop_flag.is_set():
                    next_at += interval
                    time.sleep(max(0, next_at - time.monotonic()))
                    frame = self._grab(sct)
                    t = time.monotonic()
                    self.last_frame = frame
                    self.frames += 1
                    self.process(frame, t)
        except Exception as e:
            self.status = f"lỗi minimap: {e}"
        else:
            self.status = "đã dừng"

    def stop(self):
        self.stop_flag.set()

    def who_jumped(self, t_event):
        """Các tướng có bước nhảy >= JUMP_PX trong [t - WINDOW_BEFORE, t + WINDOW_AFTER].
        Trả về [(champ, px)] sắp xếp theo px giảm dần."""
        side = min(self.rect[2], self.rect[3])
        jump_px, jump_max, tol = side * JUMP_PX_FRAC, side * JUMP_MAX_FRAC, side * STABLE_TOL_FRAC
        out = []
        with self.lock:
            for champ, h in self.history.items():
                pts = [(t, x, y) for t, x, y, s in h
                       if t_event - WINDOW_BEFORE - STABLE_BEFORE <= t <= t_event + WINDOW_AFTER + 0.3]
                best = 0.0
                for (t1, x1, y1), (t2, x2, y2) in zip(pts, pts[1:]):
                    if not (t_event - WINDOW_BEFORE <= t2 <= t_event + WINDOW_AFTER) or not 0 < t2 - t1 <= JUMP_MAX_DT:
                        continue
                    d = float(np.hypot(x2 - x1, y2 - y1))
                    if not jump_px <= d <= jump_max:
                        continue
                    # trước: đứng yên quanh chỗ cũ; sau: ở lại chỗ mới (loại nhầm danh tính 1-2 khung)
                    before = [(x, y) for t, x, y in pts if t1 - STABLE_BEFORE <= t < t1]
                    after = [(x, y) for t, x, y in pts if t2 < t <= t2 + 0.3]
                    if len(before) < 2 or max(np.hypot(x - x1, y - y1) for x, y in before) > tol:
                        continue
                    if after and np.hypot(np.mean([a[0] for a in after]) - x2,
                                          np.mean([a[1] for a in after]) - y2) > tol:
                        continue
                    best = max(best, d)
                if best:
                    out.append((champ, best))
        return sorted(out, key=lambda r: -r[1])

    def snapshot(self, path):
        frame = self.last_frame
        if frame is None or cv2 is None:
            return False
        img = frame.copy()
        for x, y, r in self.last_rings:
            cv2.circle(img, (int(x), int(y)), int(r), (255, 255, 0), 1)
        with self.lock:
            for champ, h in self.history.items():
                if h and time.monotonic() - h[-1][0] < 1.0:
                    t, x, y, s = h[-1]
                    cv2.putText(img, f"{champ[:6]} {s:.2f}", (int(x) - 12, int(y) - 14),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 0), 1)
        cv2.imwrite(path, img)
        return True


if __name__ == "__main__":  # chạy thử: in vị trí và bước nhảy
    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "champion")
    names = sys.argv[1:] or ["Zed", "LeeSin", "Yasuo", "Kaisa", "Darius"]
    tr = MinimapTracker()
    tr.set_enemies({n: os.path.join(cache, n + ".png") for n in names})
    tr.start()
    print("rect", tr.rect, "bán kính vòng", tr.r_min, tr.r_max)
    try:
        while True:
            time.sleep(1)
            with tr.lock:
                line = "  ".join(f"{c}:({h[-1][1]:.0f},{h[-1][2]:.0f}) {h[-1][3]:.2f}" for c, h in tr.history.items() if h)
            print(f"\r{tr.status} {tr.frames} khung, {len(tr.last_rings)} vòng | {line}      ", end="", flush=True)
            j = tr.who_jumped(time.monotonic() - 0.5)
            if j:
                print("\nNHẢY:", j)
    except KeyboardInterrupt:
        tr.stop()
        tr.snapshot("minimap_snapshot.png")
