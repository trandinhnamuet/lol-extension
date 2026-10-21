"""Ghép mốc Flash (HUD) + điểm NCC (compare_<template>.csv) với vị trí tướng (positions.csv của
lượt replay_positions.py) để biết mỗi lần Flash cách camera bao xa.

    python flash_distance.py sessions/replay_<x> sessions/positions_<x> [--camera "SRV TranKhoaCu"]

Khoảng cách tính bằng đơn vị bản đồ (màn hình 1080p ở zoom mặc định rộng ~1900 x 1100 đơn vị).
Vị trí lấy nội suy theo giây replay (time), các mẫu cách nhau ~10*interval giây.
Lưu flash_distance.csv trong phiên âm thanh.
"""
import argparse
import csv
import json
import os

import numpy as np


def load_positions(path):
    pos = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if float(r["time"]) <= 0.5:
                continue
            pos.setdefault(r["player"], []).append((float(r["time"]), float(r["x"]), float(r["z"])))
    return {k: np.array(v) for k, v in pos.items()}


def at(pos, name, t):
    p = pos[name]
    return np.interp(t, p[:, 0], p[:, 1]), np.interp(t, p[:, 0], p[:, 2])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session")
    ap.add_argument("positions")
    ap.add_argument("--template", default="flash")
    ap.add_argument("--camera", help="người chơi mà camera gắn vào trong phiên âm thanh (mặc định: replay.json)")
    args = ap.parse_args()

    with open(os.path.join(args.session, "replay.json"), encoding="utf-8") as f:
        meta = json.load(f)
    camera = args.camera or meta["render"].get("selectionName") or meta["me"].split("#")[0]
    pos = load_positions(os.path.join(args.positions, "positions.csv"))
    if camera not in pos:
        raise SystemExit(f"không có vị trí của {camera}; có: {list(pos)}")
    # giờ game (gameTime) ~ giây replay (time); phiên âm thanh có game.csv: t -> gameTime
    with open(os.path.join(args.session, "game.csv"), newline="") as f:
        g = list(csv.DictReader(f))
    gt_t = np.array([float(r["t"]) for r in g])
    gt_g = np.array([float(r["gameTime"]) for r in g])
    with open(os.path.join(args.session, f"compare_{args.template}.csv"), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    out = []
    print(f"camera gắn vào {camera}\n{'game':>6} {'cách':>6} {'NCC':>6} {'RMS+':>5}  ai")
    for r in rows:
        t = float(r["t"])
        rt = float(np.interp(t, gt_t, gt_g)) - 0.25  # HUD tối đi sau khi dùng ~0-0,25 s
        name = r["player"]
        if name not in pos:
            continue
        cx, cz = at(pos, camera, rt)
        x, z = at(pos, name, rt)
        d = float(np.hypot(x - cx, z - cz))
        rise = float(r["rms_peak"]) - float(r["rms_base"])
        out.append({**r, "dist": f"{d:.0f}"})
        print(f"{int(float(r['gameTime'])) // 60}:{int(float(r['gameTime'])) % 60:02d} {d:6.0f} {float(r['ncc_max']):6.3f} {rise:5.1f}  {r['team']:5s} {r['champion']:12s} {name}")
    d = np.array([float(o["dist"]) for o in out])
    n = np.array([float(o["ncc_max"]) for o in out])
    for lo, hi in ((0, 1000), (1000, 2000), (2000, 4000), (4000, 1e9)):
        m = (d >= lo) & (d < hi)
        if m.any():
            print(f"cách {lo:>5.0f}-{min(hi, 99999):<5.0f}: {m.sum():2d} lần, NCC trung vị {np.median(n[m]):.3f}, "
                  f"min {n[m].min():.3f}, max {n[m].max():.3f}, >=0.5: {(n[m] >= 0.5).sum()}")
    path = os.path.join(args.session, "flash_distance.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print("Đã ghi", path)


if __name__ == "__main__":
    main()
