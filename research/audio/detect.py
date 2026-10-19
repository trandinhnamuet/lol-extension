"""Dò mẫu âm thanh trong một phiên đã ghi, kèm ảnh màn hình quanh mỗi lần dò được để kiểm tra.

    python detect.py sessions/<x> --template flash --thr 0.5

Kết quả trong sessions/<x>/detect_<template>/
    detections.csv      t, score, gameTime, frame
    NNN_<t>s.jpg        ảnh màn hình tại t-0.5 | t | t+0.5 (nếu phiên có ảnh)
    scores.npy          điểm NCC từng khung 10ms (để vẽ / chỉnh ngưỡng)
"""
import argparse
import csv
import os
import sys

import numpy as np
from scipy.signal import find_peaks

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HOP, SR, TEMPLATES_DIR, features, frame_time, load_template, load_wav, ncc  # noqa: E402


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def game_time_at(rows, t):
    if not rows:
        return None
    ts = np.array([float(r["t"]) for r in rows])
    gt = np.array([float(r["gameTime"]) for r in rows])
    if t < ts[0] or t > ts[-1] + 5:
        return None
    return float(np.interp(t, ts, gt))


def fmt(seconds):
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def contact_sheet(frames, t, out_path):
    import cv2
    if not frames:
        return None
    ts = np.array([float(r["t"]) for r in frames])
    tiles = []
    for dt in (-0.5, 0, 0.5):
        i = int(np.argmin(np.abs(ts - (t + dt))))
        img = cv2.imread(os.path.join(os.path.dirname(out_path), "..", "frames", frames[i]["file"]))
        if img is None:
            return None
        cv2.putText(img, f"{t + dt:.1f}s", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        tiles.append(img)
    cv2.imwrite(out_path, np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 75])
    return frames[int(np.argmin(np.abs(ts - t)))]["file"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", help="thư mục phiên, hoặc một file .wav")
    ap.add_argument("--template", required=True, help="tên mẫu trong templates/, vd flash")
    ap.add_argument("--thr", type=float, default=0.5, help="ngưỡng NCC")
    ap.add_argument("--min-gap", type=float, default=0.5, help="giây tối thiểu giữa hai lần dò")
    ap.add_argument("--no-images", action="store_true")
    args = ap.parse_args()

    if args.session.lower().endswith(".wav"):
        session, wav = os.path.dirname(args.session), args.session
    else:
        session, wav = args.session, os.path.join(args.session, "audio.wav")
    template, pre, length = load_template(os.path.join(TEMPLATES_DIR, args.template + ".npz"))

    print("Đang đọc", wav)
    y = load_wav(wav)
    scores = ncc(features(y), template)
    print(f"Thời lượng {len(y) / SR / 60:.1f} phút, {len(scores)} khung")
    pct = np.percentile(scores, [50, 99, 99.9, 99.99])
    print(f"NCC nền: trung vị {pct[0]:.3f}  99% {pct[1]:.3f}  99.9% {pct[2]:.3f}  "
          f"99.99% {pct[3]:.3f}  max {scores.max():.3f}")

    peaks, props = find_peaks(scores, height=args.thr, distance=int(args.min_gap * SR / HOP))
    out_dir = os.path.join(session, f"detect_{args.template}")
    os.makedirs(out_dir, exist_ok=True)
    np.save(os.path.join(out_dir, "scores.npy"), scores)
    game_rows = read_csv(os.path.join(session, "game.csv"))
    frames = [] if args.no_images else read_csv(os.path.join(session, "frames.csv"))

    print(f"\n{len(peaks)} lần vượt ngưỡng {args.thr}:")
    with open(os.path.join(out_dir, "detections.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "score", "gameTime", "frame"])
        for n, (i, score) in enumerate(zip(peaks, props["peak_heights"])):
            t = frame_time(i) + pre  # thời điểm onset
            gt = game_time_at(game_rows, t)
            frame = contact_sheet(frames, t, os.path.join(out_dir, f"{n:03d}_{t:.1f}s.jpg"))
            writer.writerow([f"{t:.2f}", f"{score:.3f}", "" if gt is None else f"{gt:.1f}", frame or ""])
            print(f"  {n:3d}  {t:8.2f}s  NCC {score:.3f}" + (f"  game {fmt(gt)}" if gt is not None else ""))
    print(f"\nKết quả trong {out_dir}")


if __name__ == "__main__":
    main()
