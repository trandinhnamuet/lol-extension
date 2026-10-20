"""CNN nhỏ nhận ra Flash trên log-mel, học từ các phiên replay có flash_events.csv (mốc HUD).

    python train_cnn.py --train sessions/replay_A sessions/replay_B --test sessions/replay_C
    python train_cnn.py --cv sessions/replay_*            # leave-one-match-out trên mọi phiên

Không cần căn onset: cửa sổ 1 s (100 khung) là "dương" nếu chứa trọn [t_hud - 0.6, t_hud + 0.1]
(tiếng Flash nằm trong đó; HUD tối đi sau tiếng tới ~0,5 s), "âm" nếu cách mọi mốc HUD > 1,5 s.
Mạng: 4 lớp conv + global max pool theo thời gian/tần số, nên tự tìm onset trong cửa sổ.
Dò: trượt cửa sổ bước 0,05 s, lấy đỉnh xác suất cách nhau >= 1 s; đúng nếu cách t_hud - 0.35 <= 1 s.

Log-mel mỗi phiên được cache ở <phiên>/logmel.npy (64 x T float32, 100 khung/giây).
Đầu vào 2 kênh: log-mel + delta 30 ms. --mine: huấn luyện 2 giai đoạn, giai đoạn 2 thêm "âm khó" là
các đỉnh p cao không gần mốc HUD trên chính phiên huấn luyện (hard-negative mining).
Lưu mô hình: models/flash_cnn.pt (khi có --test hoặc --save).
"""
import argparse
import csv
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as Fnn
from scipy.signal import find_peaks

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HOP, SR, logmel, load_wav  # noqa: E402

FPS = SR / HOP  # 100 khung / giây
W = 100  # cửa sổ 1 s
POS_PRE, POS_POST = 0.6, 0.1  # tiếng Flash nằm trong [t_hud - 0.6, t_hud + 0.1]
NEG_GAP = 1.5
MATCH = 1.0
CENTER = 0.35  # mốc "thật" ước lượng = t_hud - 0.35
HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "models")


def session_logmel(path):
    cache = os.path.join(path, "logmel.npy")
    if os.path.exists(cache):
        return np.load(cache)
    print("  tính log-mel", path, flush=True)
    X = logmel(load_wav(os.path.join(path, "audio.wav"))).astype(np.float32)
    np.save(cache, X)
    return X


def normalize(X):
    """Chuẩn hóa từng băng theo trung vị / IQR của phiên (nền khác nhau giữa các máy, mức âm lượng)."""
    med = np.median(X, axis=1, keepdims=True)
    iqr = np.percentile(X, 75, axis=1, keepdims=True) - np.percentile(X, 25, axis=1, keepdims=True) + 1e-3
    return ((X - med) / iqr).astype(np.float32)


def load_events(path):
    with open(os.path.join(path, "flash_events.csv"), newline="", encoding="utf-8") as f:
        return np.array([float(r["t"]) for r in csv.DictReader(f)])


def make_windows(X, ev, rng, n_neg=4000):
    T = X.shape[1]
    pos = []
    for t in ev:
        s0, s1 = int((t + POS_POST) * FPS) - W, int((t - POS_PRE) * FPS)
        pos += [s for s in range(s0, s1 + 1) if 0 <= s and s + W <= T]
    far = np.ones(T - W, bool)
    for t in ev:
        far[max(0, int((t - NEG_GAP) * FPS) - W):int((t + NEG_GAP) * FPS)] = False
    cand = np.flatnonzero(far)
    neg = rng.choice(cand, size=min(n_neg, len(cand)), replace=False)
    starts = np.array(pos + list(neg))
    y = np.r_[np.ones(len(pos)), np.zeros(len(neg))].astype(np.float32)
    return starts, y


def with_delta(w):
    """(64, W) -> (2, 64, W): log-mel và delta 30 ms (nhấn phần tấn công của tiếng)."""
    d = np.zeros_like(w)
    d[:, 3:] = w[:, 3:] - w[:, :-3]
    return np.stack([w, d])


class FlashCNN(nn.Module):
    def __init__(self):
        super().__init__()
        ch = (2, 16, 32, 64, 64)
        self.convs = nn.ModuleList([nn.Conv2d(ch[i], ch[i + 1], 3, padding=1) for i in range(4)])
        self.bns = nn.ModuleList([nn.BatchNorm2d(ch[i + 1]) for i in range(4)])
        self.fc = nn.Linear(64, 1)

    def forward(self, x):  # x: (B, 2, 64, W)
        for i, (c, b) in enumerate(zip(self.convs, self.bns)):
            x = Fnn.relu(b(c(x)))
            if i < 3:
                x = Fnn.max_pool2d(x, 2)
        x = x.amax(dim=(2, 3))  # global max: onset ở đâu trong cửa sổ cũng được
        return self.fc(x).squeeze(1)


class WindowSet(torch.utils.data.Dataset):
    def __init__(self, items, train):
        self.items = items  # (X, start, y)
        self.train = train

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        X, s, y = self.items[i]
        w = X[:, s:s + W]
        if self.train:
            w = w + np.random.uniform(-0.5, 0.5)  # lệch âm lượng
        return torch.from_numpy(with_delta(np.ascontiguousarray(w))), torch.tensor(y)


def mine_hard(model, sessions, device, thr=0.3, per_session=400):
    """Đỉnh p >= thr trên phiên huấn luyện mà cách mọi mốc HUD > NEG_GAP: âm khó, kèm dịch ±10 khung."""
    hard = {}
    for path, X, ev in sessions:
        st, pr = score(model, X, device)
        t = (st + W) / FPS - 0.5
        peaks, props = find_peaks(pr, height=thr, distance=int(FPS / 5))
        far = [p for p in peaks if len(ev) == 0 or np.min(np.abs(ev - CENTER - t[p])) > NEG_GAP]
        far = sorted(far, key=lambda p: -pr[p])[:per_session]
        starts = []
        for p in far:
            for d in (-10, -5, 0, 5, 10):
                s0 = int(st[p]) + d
                if 0 <= s0 and s0 + W <= X.shape[1]:
                    starts.append(s0)
        hard[path] = starts
        print(f"  âm khó {os.path.basename(path)}: {len(far)} đỉnh -> {len(starts)} cửa sổ")
    return hard


def train(sessions, epochs, device, seed=0, hard=None):
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    items = []
    for path, X, ev in sessions:
        starts, y = make_windows(X, ev, rng)
        items += [(X, int(s), float(v)) for s, v in zip(starts, y)]
        if hard and path in hard:
            items += [(X, int(s), 0.0) for s in hard[path]]
        print(f"  {os.path.basename(path)}: {int(y.sum())} dương ({len(ev)} Flash), {int((1 - y).sum())} âm"
              + (f" + {len(hard[path])} âm khó" if hard and path in hard else ""))
    ys = np.array([it[2] for it in items])
    pos_weight = torch.tensor((1 - ys).sum() / max(1, ys.sum()), device=device)
    loader = torch.utils.data.DataLoader(WindowSet(items, True), batch_size=128, shuffle=True, num_workers=0)
    model = FlashCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    for ep in range(epochs):
        model.train()
        tot = n = 0
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            loss = Fnn.binary_cross_entropy_with_logits(model(xb), yb, pos_weight=pos_weight)
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item() * len(xb)
            n += len(xb)
        sched.step()
        print(f"  epoch {ep + 1}/{epochs} loss {tot / n:.4f}", flush=True)
    return model


@torch.no_grad()
def score(model, X, device, hop=5):
    model.eval()
    T = X.shape[1]
    starts = np.arange(0, T - W, hop)
    out = np.zeros(len(starts), np.float32)
    B = 512
    for i in range(0, len(starts), B):
        idx = starts[i:i + B]
        xb = torch.from_numpy(np.stack([with_delta(X[:, s:s + W]) for s in idx])).to(device)
        out[i:i + B] = torch.sigmoid(model(xb)).cpu().numpy()
    return starts, out


def evaluate(starts, prob, ev, label, hop=5):
    t = (starts + W) / FPS - 0.5  # giữa cửa sổ
    dur = (starts[-1] + W) / FPS
    truth = ev - CENTER
    print(f"\n{label}: {len(ev)} Flash, {dur / 60:.1f} phút")
    print(f"{'ngưỡng p':>9} {'bắt':>4} {'sót':>4} {'báo sai':>8} {'sai/10ph':>9}")
    rows = []
    for p in (0.5, 0.7, 0.9, 0.95, 0.98):
        peaks, _ = find_peaks(prob, height=p, distance=int(FPS / hop))
        pt = t[peaks]
        hit = sum(1 for h in truth if len(pt) and np.min(np.abs(pt - h)) <= MATCH)
        fp = sum(1 for x in pt if len(truth) == 0 or np.min(np.abs(truth - x)) > MATCH)
        rows.append((p, hit, len(ev) - hit, fp, fp / (dur / 600)))
        print(f"{p:9.2f} {hit:4d} {len(ev) - hit:4d} {fp:8d} {fp / (dur / 600):9.1f}")
    return rows


def train_two_stage(sessions, epochs, device, mine):
    model = train(sessions, epochs, device)
    if not mine:
        return model
    print("  -- giai đoạn 2: hard-negative mining --")
    hard = mine_hard(model, sessions, device)
    return train(sessions, epochs, device, seed=1, hard=hard)


def load_sessions(paths):
    out = []
    for p in paths:
        p = p.rstrip("/\\")
        if not os.path.exists(os.path.join(p, "flash_events.csv")):
            print("  bỏ qua (chưa có flash_events.csv):", p)
            continue
        out.append((p, normalize(session_logmel(p)), load_events(p)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", nargs="*", default=[])
    ap.add_argument("--test", nargs="*", default=[])
    ap.add_argument("--cv", nargs="*", default=[], help="leave-one-match-out trên các phiên này")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--mine", action="store_true", help="2 giai đoạn: thêm âm khó từ chính phiên huấn luyện")
    ap.add_argument("--folds", type=int, default=0, help="--cv: chỉ chấm N phiên đầu (so sánh nhanh)")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("Thiết bị:", device)

    if args.cv:
        sessions = load_sessions(args.cv)
        total = {}
        for k, (path, X, ev) in enumerate(sessions):
            if args.folds and k >= args.folds:
                break
            print(f"\n=== Giữ lại {os.path.basename(path)} ===")
            model = train_two_stage([s for i, s in enumerate(sessions) if i != k], args.epochs, device, args.mine)
            st, pr = score(model, X, device)
            np.save(os.path.join(path, "cnn_prob.npy"), np.stack([st, pr]))
            for p, hit, miss, fp, rate in evaluate(st, pr, ev, os.path.basename(path)):
                a = total.setdefault(p, [0, 0, 0, 0.0])
                a[0] += hit
                a[1] += miss
                a[2] += fp
                a[3] += (st[-1] + W) / FPS
        print(f"\nTổng ({min(len(sessions), args.folds or len(sessions))} trận, mỗi trận do mô hình không thấy trận đó chấm):")
        print(f"{'ngưỡng p':>9} {'bắt':>4} {'sót':>4} {'báo sai':>8} {'sai/10ph':>9}")
        for p, (hit, miss, fp, dur) in sorted(total.items()):
            print(f"{p:9.2f} {hit:4d} {miss:4d} {fp:8d} {fp / (dur / 600):9.1f}")
        return

    sessions = load_sessions(args.train)
    t0 = time.time()
    model = train_two_stage(sessions, args.epochs, device, args.mine)
    print(f"Huấn luyện {time.time() - t0:.0f} s")
    for path, X, ev in load_sessions(args.test):
        st, pr = score(model, X, device)
        np.save(os.path.join(path, "cnn_prob.npy"), np.stack([st, pr]))
        evaluate(st, pr, ev, os.path.basename(path))
    if args.save or args.test:
        os.makedirs(MODELS, exist_ok=True)
        torch.save(model.state_dict(), os.path.join(MODELS, "flash_cnn.pt"))
        print("Đã lưu", os.path.join(MODELS, "flash_cnn.pt"))


if __name__ == "__main__":
    main()
