"""Vẽ RMS, log-mel và NCC của một phiên để nhìn dữ liệu thật. Chạy từ thư mục gốc project."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join("research", "audio"))
from common import HOP, SR, TEMPLATES_DIR, features, load_template, load_wav, logmel, ncc  # noqa: E402

session, template_name, out_png = sys.argv[1], sys.argv[2], sys.argv[3]
t_from, t_to = (float(sys.argv[4]), float(sys.argv[5])) if len(sys.argv) > 5 else (0, 1e9)
y = load_wav(os.path.join(session, "audio.wav"))
y = y[int(t_from * SR):int(t_to * SR)]
X = logmel(y)
W, pre, length = load_template(os.path.join(TEMPLATES_DIR, template_name + ".npz"))
scores = ncc(features(y), W)
n = len(y) // HOP
rms = np.sqrt((y[:n * HOP].reshape(n, HOP) ** 2).mean(axis=1))

print("log-mel percentiles 1/10/50/90/99/max:",
      np.round(np.percentile(X, [1, 10, 50, 90, 99, 100]), 2))
print("template percentiles 1/50/99:", np.round(np.percentile(W, [1, 50, 99]), 2))
print("RMS dB percentiles 10/50/90/max:",
      np.round(20 * np.log10(np.percentile(rms, [10, 50, 90, 100]) + 1e-9), 1))
print("NCC percentiles 50/99/99.9/max:", np.round(np.percentile(scores, [50, 99, 99.9, 100]), 3))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

t_frames = np.arange(X.shape[1]) * HOP / SR
fig, axes = plt.subplots(3, 1, figsize=(18, 10), sharex=True)
axes[0].plot(np.arange(n) * HOP / SR, 20 * np.log10(rms + 1e-9), lw=0.6)
axes[0].set_ylabel("RMS dB")
axes[1].imshow(X, aspect="auto", origin="lower", cmap="magma",
               extent=[0, t_frames[-1], 0, X.shape[0]], vmin=np.percentile(X, 5), vmax=X.max())
axes[1].set_ylabel("mel band")
axes[2].plot(t_frames[:len(scores)] + pre, scores, lw=0.6)
axes[2].set_ylabel("NCC")
axes[2].set_xlabel("s")
axes[2].set_ylim(-0.5, 1.05)
axes[2].grid(alpha=0.3)
step = 5 if t_frames[-1] > 40 else 1
for ax in axes:
    ax.set_xticks(np.arange(0, t_frames[-1], step))
    ax.set_xticklabels([f"{t_from + v:.0f}" for v in np.arange(0, t_frames[-1], step)])
plt.tight_layout()
plt.savefig(out_png, dpi=90)
print("saved", out_png)
