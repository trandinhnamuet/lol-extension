"""So sánh cách trích đặc trưng / độ dài mẫu: biên giữa Flash thật thấp nhất và tiếng khác cao nhất."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join("research", "audio"))
from common import HOP, SR, load_wav, logmel, ncc  # noqa: E402
from make_template import find_onsets  # noqa: E402

session = sys.argv[1]
y = load_wav(os.path.join(session, "audio.wav"))
X = logmel(y)
onsets = find_onsets(y, 9, 1.5)
print("onsets:", [round(o * HOP / SR, 2) for o in onsets])
T = X.shape[1]
t_start = np.arange(T) * HOP / SR  # thời điểm bắt đầu cửa sổ


def feats(kind):
    if kind == "logmel":
        return X
    if kind == "clamp":
        return np.maximum(X, -8)
    if kind == "delta":  # thay đổi so với 30 ms trước, nhấn mạnh phần tấn công
        d = np.zeros_like(X)
        d[:, 3:] = X[:, 3:] - X[:, :-3]
        return d
    if kind == "bandnorm":  # bỏ dạng phổ tĩnh của từng băng (trừ trung vị băng trên toàn bản ghi)
        return X - np.median(X, axis=1, keepdims=True)
    raise ValueError(kind)


PRE = 0.05
print(f"{'feat':9s} {'len':>5s} {'true_min':>9s} {'true_med':>9s} {'fp_max':>7s} {'margin':>7s}")
for kind in ("logmel", "clamp", "delta", "bandnorm"):
    F = feats(kind)
    for length in (0.15, 0.25, 0.4, 0.65):
        L = int((PRE + length) * SR / HOP)
        pre_f = int(PRE * SR / HOP)
        clips = [F[:, o - pre_f:o - pre_f + L] for o in onsets if o - pre_f + L <= T]
        W = np.median(np.stack(clips), axis=0).astype(np.float32)
        s = ncc(F, W)
        ts = t_start[:len(s)] + PRE
        true = [s[(ts >= o * HOP / SR - 0.15) & (ts <= o * HOP / SR + 0.15)].max() for o in onsets]
        fp_mask = (ts <= 19.5) | ((ts >= 31.3) & (ts <= 32.9))
        fp = s[fp_mask].max()
        print(f"{kind:9s} {length:5.2f} {min(true):9.3f} {np.median(true):9.3f} {fp:7.3f} {min(true) - fp:7.3f}")
