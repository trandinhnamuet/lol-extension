"""Kiểm flash_listener.py không cần game: đưa audio.wav của một phiên replay qua đúng đường
streaming (ring buffer, log-mel numpy, chuẩn hóa chạy, ONNX, chọn đỉnh) rồi so với flash_events.csv.

    python research/audio/test_listener_offline.py sessions/replay_<x> [--thr 0.95]

In: số Flash bắt được / sót / báo sai, so với cách chấm offline (train_cnn.py) nếu có cnn_prob.npy.
"""
import argparse
import csv
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import flash_listener as fl  # noqa: E402
from common import load_wav  # noqa: E402

CENTER, MATCH = 0.35, 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--thr", type=float, default=0.95)
    args = ap.parse_args()
    s = args.session
    y = load_wav(os.path.join(s, "audio.wav"))
    with open(os.path.join(s, "flash_events.csv"), newline="", encoding="utf-8") as f:
        ev = np.array([float(r["t"]) for r in csv.DictReader(f)]) - CENTER

    events = []
    lst = fl.FlashListener(lambda t, p: events.append((t, p)), threshold=args.thr)
    lst._load_model()
    lst.t0 = 0.0
    need = fl.N_FFT + fl.HOP * (fl.W + fl.DELTA - 1)
    step = int(fl.STEP * fl.SR)
    t_start = time.perf_counter()
    probs = []
    for end in range(need, len(y), step):  # mô phỏng: mỗi 100 ms có thêm 100 ms âm thanh
        lst._write(y[end - step:end] if end > need else y[:end])
        yy, t_end = lst._last(need)
        X = fl.logmel(yy)
        lst.stats.push(X[:, -10:])
        if not lst.stats.ready():
            continue
        if t_end - lst.last_stats_update >= 2:
            lst.stats.update()
            lst.last_stats_update = t_end
        p = lst.score_window(lst.stats.normalize(X))
        lst.probs.append((t_end - 0.5, p))
        probs.append((t_end - 0.5, p))
        lst._maybe_emit()
    took = time.perf_counter() - t_start
    dur = len(y) / fl.SR
    print(f"{dur / 60:.1f} phút âm thanh, xử lý {took:.0f} s ({took / dur * 100:.1f}% thời gian thực, 1 luồng)")

    et = np.array([t for t, _ in events])
    hit = sum(1 for h in ev if len(et) and np.min(np.abs(et - h)) <= MATCH)
    fp = sum(1 for t in et if len(ev) == 0 or np.min(np.abs(ev - t)) > MATCH)
    print(f"Streaming, ngưỡng {args.thr}: bắt {hit}/{len(ev)}, báo sai {fp} ({fp / (dur / 600):.1f}/10 phút)")

    cp = os.path.join(s, "cnn_prob.npy")
    if os.path.exists(cp):
        from scipy.signal import find_peaks
        st, pr = np.load(cp)
        t = (st + 100) / 100 - 0.5
        peaks, _ = find_peaks(pr, height=args.thr, distance=20)
        pt = t[peaks]
        hit2 = sum(1 for h in ev if len(pt) and np.min(np.abs(pt - h)) <= MATCH)
        fp2 = sum(1 for x in pt if np.min(np.abs(ev - x)) > MATCH)
        print(f"Offline (train_cnn.py, mô hình kiểm chéo): bắt {hit2}/{len(ev)}, báo sai {fp2}")
    np.save(os.path.join(s, "listener_prob.npy"), np.array(probs))


if __name__ == "__main__":
    main()
