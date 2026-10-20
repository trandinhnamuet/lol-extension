"""Cắt đoạn âm thanh quanh các lần "báo sai" và "sót" của CNN để nghe kiểm tra bằng tai.

    python export_clips.py sessions/replay_<x> [--p 0.95] [--n 20] [--out clips]

Đọc <phiên>/cnn_prob.npy + flash_events.csv + audio.wav, ghi vào <phiên>/clips/:
    fp_<NN>_<game m:ss>_p<prob>.wav       đỉnh p >= ngưỡng, không có Flash HUD trong ±1,5 s
    miss_<NN>_<game m:ss>_<champ>_p<max>.wav   Flash HUD mà p quanh đó < ngưỡng
    hit_<NN>_...                          vài lần bắt đúng để so
Mỗi đoạn 2,5 s: 1,0 s trước mốc, 1,5 s sau. index.csv liệt kê tất cả.
"""
import argparse
import csv
import os
import wave

import numpy as np
from scipy.signal import find_peaks

W, FPS, CENTER, MATCH = 100, 100.0, 0.35, 1.0


def fmt(sec):
    return f"{int(sec) // 60}m{int(sec) % 60:02d}s"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session")
    ap.add_argument("--p", type=float, default=0.95)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default="clips")
    args = ap.parse_args()
    s = args.session
    st, pr = np.load(os.path.join(s, "cnn_prob.npy"))
    t = (st + W) / FPS - 0.5
    with open(os.path.join(s, "flash_events.csv"), newline="", encoding="utf-8") as f:
        ev = list(csv.DictReader(f))
    ev_t = np.array([float(e["t"]) for e in ev]) - CENTER
    with open(os.path.join(s, "game.csv"), newline="") as f:
        g = list(csv.DictReader(f))
    gt_t = np.array([float(r["t"]) for r in g])
    gt_g = np.array([float(r["gameTime"]) for r in g])

    wf = wave.open(os.path.join(s, "audio.wav"))
    rate, ch, n = wf.getframerate(), wf.getnchannels(), wf.getnframes()
    out = os.path.join(s, args.out)
    os.makedirs(out, exist_ok=True)

    def clip(name, tc):
        a, b = max(0, int((tc - 1.0) * rate)), min(n, int((tc + 1.5) * rate))
        wf.setpos(a)
        data = wf.readframes(b - a)
        with wave.open(os.path.join(out, name), "wb") as o:
            o.setnchannels(ch)
            o.setsampwidth(2)
            o.setframerate(rate)
            o.writeframes(data)

    rows = []
    peaks, _ = find_peaks(pr, height=args.p, distance=int(FPS / 5))
    fps_ = [p for p in peaks if len(ev_t) == 0 or np.min(np.abs(ev_t - t[p])) > MATCH]
    fps_ = sorted(fps_, key=lambda p: -pr[p])[:args.n]
    for i, p in enumerate(fps_):
        gt = float(np.interp(t[p], gt_t, gt_g))
        name = f"fp_{i:02d}_{fmt(gt)}_p{pr[p]:.2f}.wav"
        clip(name, t[p])
        rows.append(("fp", name, f"{t[p]:.2f}", fmt(gt), "", f"{pr[p]:.3f}"))
    misses, hits = [], []
    for e, te in zip(ev, ev_t):
        m = (t >= te - MATCH) & (t <= te + MATCH)
        pm = float(pr[m].max()) if m.any() else 0.0
        (hits if pm >= args.p else misses).append((e, te, pm))
    for i, (e, te, pm) in enumerate(sorted(misses, key=lambda x: x[2])[:args.n]):
        gt = float(e["gameTime"])
        name = f"miss_{i:02d}_{fmt(gt)}_{e['champion'].replace(chr(39), '')}_p{pm:.2f}.wav"
        clip(name, te)
        rows.append(("miss", name, f"{te:.2f}", fmt(gt), e["champion"], f"{pm:.3f}"))
    for i, (e, te, pm) in enumerate(hits[:5]):
        gt = float(e["gameTime"])
        name = f"hit_{i:02d}_{fmt(gt)}_{e['champion'].replace(chr(39), '')}_p{pm:.2f}.wav"
        clip(name, te)
        rows.append(("hit", name, f"{te:.2f}", fmt(gt), e["champion"], f"{pm:.3f}"))
    with open(os.path.join(out, "index.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["kind", "file", "t", "gameTime", "champion", "p"])
        w.writerows(rows)
    print(f"{len(fps_)} báo sai, {len(misses)} sót (ghi {min(len(misses), args.n)}), {len(hits)} đúng (ghi 5) -> {out}")


if __name__ == "__main__":
    main()
