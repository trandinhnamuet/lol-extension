"""Đối chiếu mốc Flash từ HUD replay (flash_events.csv, mốc chuẩn) với điểm NCC âm thanh
(detect_<template>/scores.npy) của cùng phiên.

    python compare_hud_audio.py sessions/replay_<x> [--template flash] [--thr 0.4 0.5 0.6]

In ra: với mỗi lần Flash (HUD) điểm NCC cao nhất trong cửa sổ [-1.5 s, +0.5 s] và RMS nền/đỉnh;
rồi với từng ngưỡng: số Flash bắt được / bỏ sót / báo sai (đỉnh NCC không gần Flash nào ±1.5 s).
Lưu compare_<template>.csv.
"""
import argparse
import csv
import os
import sys

import numpy as np
from scipy.signal import find_peaks

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HOP, SR, load_wav  # noqa: E402

PRE, POST = 1.5, 0.5  # cửa sổ quanh mốc HUD (HUD tối đi sau tiếng tới 0,25 s + trễ ảnh)
MATCH = 1.5  # đỉnh NCC cách mốc HUD trong chừng này giây thì coi là cùng một Flash


def fmt(s):
    return f"{int(s) // 60}:{int(s) % 60:02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session")
    ap.add_argument("--template", default="flash")
    ap.add_argument("--thr", type=float, nargs="+", default=[0.3, 0.4, 0.5, 0.6])
    ap.add_argument("--min-gap", type=float, default=0.5)
    args = ap.parse_args()
    s = args.session

    scores = np.load(os.path.join(s, f"detect_{args.template}", "scores.npy"))
    with open(os.path.join(s, "flash_events.csv"), newline="", encoding="utf-8") as f:
        events = list(csv.DictReader(f))
    wav = os.path.join(s, "audio.wav")
    y = load_wav(wav) if os.path.exists(wav) else None
    dur = len(scores) * HOP / SR

    print(f"{len(events)} lần Flash theo HUD, âm thanh {dur / 60:.1f} phút")
    print(f"{'game':>6} {'t':>7} {'NCC max':>8} {'tại':>7} {'RMS nền':>8} {'RMS đỉnh':>9}  ai")
    rows = []
    for e in events:
        t = float(e["t"])
        lo, hi = max(0, int((t - PRE) * SR / HOP)), min(len(scores), int((t + POST) * SR / HOP))
        seg = scores[lo:hi]
        if len(seg) == 0:
            continue
        peak = lo + int(np.argmax(seg))
        base = peak_db = float("nan")
        if y is not None:
            a = y[int(max(0, t - 2) * SR):int((t + 1) * SR)]
            n = len(a) // HOP
            if n:
                rms = 20 * np.log10(np.sqrt((a[:n * HOP].reshape(n, HOP) ** 2).mean(axis=1)) + 1e-9)
                base, peak_db = float(np.median(rms)), float(rms.max())
        row = {"t": t, "gameTime": float(e["gameTime"]), "team": e["team"], "champion": e["champion"],
               "player": e["player"], "ncc_max": float(seg.max()), "ncc_at": peak * HOP / SR,
               "rms_base": base, "rms_peak": peak_db}
        rows.append(row)
        print(f"{fmt(row['gameTime']):>6} {t:7.1f} {row['ncc_max']:8.3f} {row['ncc_at']:7.1f} {base:8.1f} {peak_db:9.1f}  "
              f"{e['team']:5s} {e['champion']:12s} {e['player']}")

    ev_t = np.array([r["t"] for r in rows])
    print(f"\nPhân bố NCC cả phiên: 99% {np.percentile(scores, 99):.3f}  99.9% {np.percentile(scores, 99.9):.3f}  "
          f"99.99% {np.percentile(scores, 99.99):.3f}  max {scores.max():.3f}")
    print(f"{'ngưỡng':>7} {'bắt được':>9} {'bỏ sót':>7} {'báo sai':>8} {'sai/10 phút':>12}")
    for thr in args.thr:
        peaks, _ = find_peaks(scores, height=thr, distance=int(args.min_gap * SR / HOP))
        pt = peaks * HOP / SR  # thời điểm đầu cửa sổ mẫu (onset - 0,05 s)
        hit = np.array([r["ncc_max"] >= thr for r in rows])
        fp = 0
        for p in pt:
            if len(ev_t) == 0 or np.min(np.abs(ev_t - p)) > MATCH:
                fp += 1
        print(f"{thr:7.2f} {int(hit.sum()):9d} {int((~hit).sum()):7d} {fp:8d} {fp / (dur / 600):12.1f}")

    out = os.path.join(s, f"compare_{args.template}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["t"])
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.3f}" if isinstance(v, float) else v) for k, v in r.items()})
    print("Đã ghi", out)


if __name__ == "__main__":
    main()
