"""Trần của bộ dò âm thanh: tỉ lệ bắt của CNN (cnn_prob.npy) theo khoảng cách Flash → camera,
dùng vị trí từ lượt replay_positions.py. Flash quá xa camera thì loa không phát, không thể bắt.

    python cnn_ceiling.py sessions/replay_<x> sessions/positions_<x> [--p 0.98]
    python cnn_ceiling.py --all            # mọi phiên replay_* có positions_<gameId>_* tương ứng

In bảng bắt/sót theo khoảng cách (0-1000, 1000-2000, 2000-3000, >3000 đơn vị bản đồ) và ghi
<phiên>/cnn_ceiling.csv (t, gameTime, champion, dist, p_max).
"""
import argparse
import csv
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SESSIONS_DIR  # noqa: E402
from flash_distance import at, load_positions  # noqa: E402

W, FPS, CENTER, MATCH = 100, 100.0, 0.35, 1.0
BINS = ((0, 1000), (1000, 2000), (2000, 3000), (3000, 1e9))


def analyze(session, positions, p_thr):
    with open(os.path.join(session, "replay.json"), encoding="utf-8") as f:
        meta = json.load(f)
    camera = meta["render"].get("selectionName") or meta["me"].split("#")[0]
    pos = load_positions(os.path.join(positions, "positions.csv"))
    if camera not in pos:
        print("  không có vị trí của", camera)
        return []
    with open(os.path.join(session, "game.csv"), newline="") as f:
        g = list(csv.DictReader(f))
    gt_t = np.array([float(r["t"]) for r in g])
    gt_g = np.array([float(r["gameTime"]) for r in g])
    st, pr = np.load(os.path.join(session, "cnn_prob.npy"))
    t = (st + W) / FPS - 0.5
    rows = []
    with open(os.path.join(session, "flash_events.csv"), newline="", encoding="utf-8") as f:
        for e in csv.DictReader(f):
            te = float(e["t"])
            rt = float(np.interp(te, gt_t, gt_g)) - 0.25
            if e["player"] not in pos:
                continue
            cx, cz = at(pos, camera, rt)
            x, z = at(pos, e["player"], rt)
            d = float(np.hypot(x - cx, z - cz))
            m = (t >= te - CENTER - MATCH) & (t <= te - CENTER + MATCH)
            rows.append({"t": te, "gameTime": e["gameTime"], "champion": e["champion"], "dist": d,
                         "p_max": float(pr[m].max()) if m.any() else 0.0})
    with open(os.path.join(session, "cnn_ceiling.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["t", "gameTime", "champion", "dist", "p_max"])
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.2f}" if isinstance(v, float) else v) for k, v in r.items()})
    return rows


def report(rows, p_thr, label):
    d = np.array([r["dist"] for r in rows])
    hit = np.array([r["p_max"] >= p_thr for r in rows])
    print(f"\n{label}: {len(rows)} Flash, p >= {p_thr}")
    print(f"{'cách':>12} {'số':>4} {'bắt':>4} {'tỉ lệ':>6}")
    for lo, hi in BINS:
        m = (d >= lo) & (d < hi)
        if m.any():
            print(f"{lo:5.0f}-{min(hi, 9999):<6.0f} {m.sum():4d} {hit[m].sum():4d} {100 * hit[m].mean():5.0f}%")
    near = d < 2000
    if near.any():
        print(f"Trong 2000 đơn vị: {hit[near].sum()}/{near.sum()} = {100 * hit[near].mean():.0f}%   "
              f"ngoài: {hit[~near].sum()}/{(~near).sum()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", nargs="?")
    ap.add_argument("positions", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--p", type=float, default=0.98)
    args = ap.parse_args()
    pairs = []
    if args.all:
        for s in sorted(glob.glob(os.path.join(SESSIONS_DIR, "replay_*"))):
            gid = os.path.basename(s).split("_")[1]
            ps = sorted(glob.glob(os.path.join(SESSIONS_DIR, f"positions_{gid}_*")))
            if ps and os.path.exists(os.path.join(s, "cnn_prob.npy")):
                pairs.append((s, ps[-1]))
    else:
        pairs = [(args.session, args.positions)]
    total = []
    for s, p in pairs:
        rows = analyze(s, p, args.p)
        report(rows, args.p, os.path.basename(s))
        total += rows
    if len(pairs) > 1:
        report(total, args.p, f"Tổng {len(pairs)} trận")


if __name__ == "__main__":
    main()
