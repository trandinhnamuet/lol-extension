"""Mốc Flash của chính người chơi từ HUD (ô D tối đi khi hồi), đối chiếu với điểm NCC âm thanh."""
import csv
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join("research", "audio"))
from common import HOP, SR  # noqa: E402

session = sys.argv[1]
template = sys.argv[2] if len(sys.argv) > 2 else "flash"
D_SLOT = (slice(499, 515), slice(492, 508))  # y, x trong khung 960x540
LEVEL_RING = (slice(500, 530), slice(366, 384))  # vòng vàng cấp độ: có -> đang trong game

with open(os.path.join(session, "frames.csv"), newline="") as f:
    frames = list(csv.DictReader(f))
with open(os.path.join(session, "game.csv"), newline="") as f:
    game = list(csv.DictReader(f))
gt_t = np.array([float(r["t"]) for r in game])
gt_g = np.array([float(r["gameTime"]) for r in game])


def yellow(region):
    b, g, r = region[..., 0].astype(float), region[..., 1].astype(float), region[..., 2].astype(float)
    return float(((r + g) / 2 - b).mean())


rows = []
for r in frames:
    img = cv2.imread(os.path.join(session, "frames", r["file"]))
    if img is None:
        continue
    rows.append((float(r["t"]), yellow(img[D_SLOT]), yellow(img[LEVEL_RING])))
rows = np.array(rows)
t, d_yellow, ring = rows.T
print(f"{len(rows)} khung")
print("D-slot yellow percentiles 5/25/50/75/95:", np.round(np.percentile(d_yellow, [5, 25, 50, 75, 95]), 1))

# icon Flash sẵn sàng rất vàng (~42); đang hồi hoặc không trong game thì thấp
thr = 30
ready = d_yellow > thr
events = []
for i in range(8, len(rows) - 8):
    # sáng ổn định 2s trước, tối ổn định 2s sau -> vừa dùng Flash (loại nhấp nháy / Alt+Tab)
    if ready[i - 8:i].all() and not ready[i:i + 8].any():
        events.append(t[i])
print(f"\nNgưỡng vàng {thr}. Flash của bạn (sáng -> tối):")

scores_path = os.path.join(session, f"detect_{template}", "scores.npy")
scores = np.load(scores_path) if os.path.exists(scores_path) else None
for te in events:
    gtime = float(np.interp(te, gt_t, gt_g))
    line = f"  t={te:8.2f}s  game {int(gtime) // 60}:{int(gtime) % 60:02d}"
    if scores is not None:
        lo, hi = int((te - 1.5) * SR / HOP), int((te + 0.5) * SR / HOP)
        seg = scores[max(0, lo):hi]
        peak = int(np.argmax(seg)) + max(0, lo)
        line += f"   NCC max trong [-1.5s,+0.5s] = {seg.max():.3f} tại {peak * HOP / SR:.2f}s"
    print(line)

np.save(os.path.join(session, "own_flash_events.npy"), np.array(events))
