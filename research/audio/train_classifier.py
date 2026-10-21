"""Thử bộ phân loại tuyến tính (logistic regression trên cửa sổ đặc trưng delta log-mel) thay cho
so mẫu NCC đơn, học từ các phiên replay có mốc Flash chuẩn (flash_events.csv + compare_flash.csv).

    python train_classifier.py --train sessions/replay_A --test sessions/replay_B
    python train_classifier.py --train sessions/replay_A            # kiểm chéo leave-one-out trên A

Dương: cửa sổ L khung bắt đầu tại onset (cột ncc_at trong compare_flash.csv) ± 2 khung.
Âm: mọi cửa sổ cách onset > 1 s, lấy ngẫu nhiên + các đỉnh NCC giả (khó).
Kết quả trên phiên test: số Flash bắt được / báo sai theo ngưỡng xác suất, so với NCC.
"""
import argparse
import csv
import os
import sys

import numpy as np
from scipy.optimize import minimize
from scipy.signal import find_peaks

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HOP, SR, TEMPLATES_DIR, features, load_template, load_wav, ncc  # noqa: E402

MATCH = 1.5


def load_session(path, L):
    y = load_wav(os.path.join(path, "audio.wav"))
    F = features(y)
    with open(os.path.join(path, "compare_flash.csv"), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    onsets = np.array([int(round(float(r["ncc_at"]) * SR / HOP)) for r in rows])
    hud_t = np.array([float(r["t"]) for r in rows])
    return F, onsets, hud_t


def windows(F, starts, L):
    return np.stack([F[:, s:s + L].ravel() for s in starts if 0 <= s and s + L <= F.shape[1]])


def make_set(F, onsets, L, template, rng, n_rand=3000, shifts=(-2, -1, 0, 1, 2)):
    pos = windows(F, [o + d for o in onsets for d in shifts], L)
    T = F.shape[1] - L
    far = np.ones(T, bool)
    for o in onsets:
        far[max(0, o - 100):o + 100] = False
    cand = np.flatnonzero(far)
    rand = rng.choice(cand, size=min(n_rand, len(cand)), replace=False)
    scores = ncc(F, template)
    peaks, _ = find_peaks(scores, height=0.3, distance=20)
    hard = [p for p in peaks if far[min(p, T - 1)]]
    neg = windows(F, np.concatenate([rand, hard]), L)
    print(f"  dương {len(pos)} (từ {len(onsets)} Flash), âm {len(neg)} (khó {len(hard)})")
    return pos, neg


def fit(X, yv, lam=1.0):
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Z = (X - mu) / sd
    Z = np.hstack([Z, np.ones((len(Z), 1))])
    w_pos = (yv == 0).mean() / (yv == 1).mean()  # cân bằng lớp
    wt = np.where(yv == 1, w_pos, 1.0)

    def loss(w):
        z = Z @ w
        p = 1 / (1 + np.exp(-z))
        eps = 1e-9
        ll = -(wt * (yv * np.log(p + eps) + (1 - yv) * np.log(1 - p + eps))).sum() / wt.sum()
        g = Z.T @ (wt * (p - yv)) / wt.sum()
        reg = lam * (w[:-1] ** 2).sum() / len(Z)
        g[:-1] += 2 * lam * w[:-1] / len(Z)
        return ll + reg, g

    res = minimize(loss, np.zeros(Z.shape[1]), jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return res.x, mu, sd


def score_all(F, L, w, mu, sd, step=1):
    T = F.shape[1] - L + 1
    out = np.full(T, -50.0)
    B = 2000
    for s0 in range(0, T, B):
        idx = np.arange(s0, min(T, s0 + B))
        X = np.stack([F[:, s:s + L].ravel() for s in idx])
        Z = (X - mu) / sd
        out[idx] = Z @ w[:-1] + w[-1]
    return out


def evaluate(logit, hud_t, L, label):
    t = np.arange(len(logit)) * HOP / SR
    dur = len(logit) * HOP / SR
    print(f"\n{label}: {len(hud_t)} Flash, {dur / 60:.1f} phút")
    print(f"{'ngưỡng p':>9} {'bắt':>4} {'sót':>4} {'báo sai':>8} {'sai/10ph':>9}")
    for p in (0.5, 0.7, 0.9, 0.95, 0.99):
        thr = np.log(p / (1 - p))
        peaks, _ = find_peaks(logit, height=thr, distance=50)
        pt = t[peaks]
        hit = sum(1 for h in hud_t if len(pt) and np.min(np.abs(pt - h)) <= MATCH)
        fp = sum(1 for x in pt if np.min(np.abs(hud_t - x)) > MATCH)
        print(f"{p:9.2f} {hit:4d} {len(hud_t) - hit:4d} {fp:8d} {fp / (dur / 600):9.1f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", nargs="+", required=True)
    ap.add_argument("--test", nargs="*", default=[])
    ap.add_argument("--lam", type=float, default=10.0)
    args = ap.parse_args()
    template, pre, length = load_template(os.path.join(TEMPLATES_DIR, "flash.npz"))
    L = template.shape[1]
    rng = np.random.default_rng(0)

    train = [(p, *load_session(p, L)) for p in args.train]
    if not args.test:
        # leave-one-out trên từng Flash của phiên đầu
        path, F, onsets, hud_t = train[0]
        print("Kiểm chéo leave-one-out trên", path)
        pos_all, neg = make_set(F, onsets, L, template, rng)
        hits = []
        for k in range(len(onsets)):
            keep = np.array([i // 5 != k for i in range(len(pos_all))])
            X = np.vstack([pos_all[keep], neg])
            yv = np.r_[np.ones(keep.sum()), np.zeros(len(neg))]
            w, mu, sd = fit(X, yv, args.lam)
            o = onsets[k]
            seg = np.stack([F[:, s:s + L].ravel() for s in range(o - 100, o + 50)])
            z = ((seg - mu) / sd) @ w[:-1] + w[-1]
            hits.append(z.max())
        hits = np.array(hits)
        p = 1 / (1 + np.exp(-hits))
        print("Xác suất tại từng Flash (giữ lại khi huấn luyện):", np.round(np.sort(p), 2))
        X = np.vstack([pos_all, neg])
        yv = np.r_[np.ones(len(pos_all)), np.zeros(len(neg))]
        w, mu, sd = fit(X, yv, args.lam)
        logit = score_all(F, L, w, mu, sd)
        evaluate(logit, hud_t, L, "Trên chính phiên huấn luyện (lạc quan)")
        return

    Xs, ys = [], []
    for path, F, onsets, _ in train:
        print("Huấn luyện:", path)
        pos, neg = make_set(F, onsets, L, template, rng)
        Xs += [pos, neg]
        ys += [np.ones(len(pos)), np.zeros(len(neg))]
    w, mu, sd = fit(np.vstack(Xs), np.concatenate(ys), args.lam)
    for path in args.test:
        F, onsets, hud_t = load_session(path, L)
        logit = score_all(F, L, w, mu, sd)
        evaluate(logit, hud_t, L, f"Test {path}")
        scores = ncc(F, template)
        print("  So với NCC:")
        t = np.arange(len(scores)) * HOP / SR
        dur = len(scores) * HOP / SR
        for thr in (0.5, 0.6, 0.7):
            peaks, _ = find_peaks(scores, height=thr, distance=50)
            pt = t[peaks]
            hit = sum(1 for h in hud_t if len(pt) and np.min(np.abs(pt - h)) <= MATCH)
            fp = sum(1 for x in pt if np.min(np.abs(hud_t - x)) > MATCH)
            print(f"  NCC {thr:.1f}: bắt {hit}/{len(hud_t)}, báo sai {fp} ({fp / (dur / 600):.1f}/10ph)")
        np.save(os.path.join(path, "clf_logit.npy"), logit)


if __name__ == "__main__":
    main()
