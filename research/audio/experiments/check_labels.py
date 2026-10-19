"""Đối chiếu nhãn Flash (giờ game) với điểm NCC và mức âm thanh quanh mốc đó."""
import csv
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join("research", "audio"))
from common import HOP, SR, load_wav  # noqa: E402

session = sys.argv[1]
with open(os.path.join(session, "game.csv"), newline="") as f:
    game = list(csv.DictReader(f))
gt_t = np.array([float(r["t"]) for r in game])
gt_g = np.array([float(r["gameTime"]) for r in game])
scores = np.load(os.path.join(session, "detect_flash", "scores.npy"))
y = load_wav(os.path.join(session, "audio.wav"))
with open(os.path.join(session, "frames.csv"), newline="") as f:
    frames = list(csv.DictReader(f))
ft = np.array([float(r["t"]) for r in frames])

out_dir = os.path.join(session, "labels_check")
os.makedirs(out_dir, exist_ok=True)
with open(os.path.join(session, "labels.csv"), newline="", encoding="utf-8") as f:
    labels = list(csv.DictReader(f))

print(f"{'game':>6} {'t (s)':>8} {'NCC max':>8} {'tại':>8}  {'RMS nền':>8} {'RMS đỉnh':>9}  champion")
for lb in labels:
    m, s = lb["gameTime"].split(":")
    g = int(m) * 60 + int(s)
    t = float(np.interp(g, gt_g, gt_t))
    lo, hi = int((t - 2) * SR / HOP), int((t + 3) * SR / HOP)
    seg = scores[lo:hi]
    peak = lo + int(np.argmax(seg))
    a = y[int((t - 2) * SR):int((t + 3) * SR)]
    n = len(a) // HOP
    rms = 20 * np.log10(np.sqrt((a[:n * HOP].reshape(n, HOP) ** 2).mean(axis=1)) + 1e-9)
    print(f"{lb['gameTime']:>6} {t:8.1f} {seg.max():8.3f} {peak * HOP / SR:8.1f}  {np.median(rms):8.1f} {rms.max():9.1f}  {lb['champion']}")
    # ảnh 8 khung từ t-1 đến t+1 (4 fps) để xem Flash có trong khung hình không
    idx = np.flatnonzero((ft >= t - 1) & (ft <= t + 1))[:8]
    tiles = []
    for i in idx:
        img = cv2.imread(os.path.join(session, "frames", frames[i]["file"]))
        cv2.putText(img, f"{ft[i]:.2f}s", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        tiles.append(cv2.resize(img, (480, 270)))
    if tiles:
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
        cv2.imwrite(os.path.join(out_dir, f"{lb['gameTime'].replace(':', 'm')}_{lb['champion']}.jpg"), grid)
print("ảnh trong", out_dir)
