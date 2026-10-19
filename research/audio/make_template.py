"""Tạo mẫu âm thanh từ bản ghi yên tĩnh (Practice Tool, tắt nhạc) có N lần dùng phép.

    python make_template.py sessions/<x>/audio.wav --name flash --count 8

Tìm N thời điểm âm thanh bùng lên mạnh nhất, cắt [onset - pre, onset + length], lấy median
log-mel của các đoạn làm mẫu, lưu templates/<name>.npz. In ra NCC của từng đoạn với mẫu
để biết các lần dùng có giống nhau không (nên > 0.7).
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HOP, SR, TEMPLATES_DIR, features, load_wav, ncc  # noqa: E402

SHIFT = 5  # khung (50 ms) tối đa dịch mỗi đoạn khi căn chỉnh


def find_onsets(y, count, min_gap):
    """Khung 10ms có năng lượng tăng vọt so với 300ms trước đó, lấy `count` cái mạnh nhất."""
    n = len(y) // HOP
    rms = np.sqrt((y[:n * HOP].reshape(n, HOP) ** 2).mean(axis=1))
    floor = np.array([rms[max(0, i - 30):i].mean() if i else 0 for i in range(n)])
    rise = rms - floor
    order = np.argsort(rise)[::-1]
    picked = []
    for i in order:
        if rise[i] <= 0:
            break
        if all(abs(i - j) * HOP / SR >= min_gap for j in picked):
            picked.append(int(i))
        if len(picked) == count:
            break
    return sorted(picked)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav")
    ap.add_argument("--name", required=True, help="tên mẫu, vd flash")
    ap.add_argument("--count", type=int, required=True, help="số lần dùng phép trong bản ghi")
    ap.add_argument("--pre", type=float, default=0.05, help="giây lấy thêm trước onset")
    ap.add_argument("--length", type=float, default=0.25, help="giây sau onset")
    ap.add_argument("--min-gap", type=float, default=1.5)
    args = ap.parse_args()

    y = load_wav(args.wav)
    onsets = find_onsets(y, args.count, args.min_gap)
    print("Onset (giây):", ", ".join(f"{i * HOP / SR:.2f}" for i in onsets))
    if len(onsets) < args.count:
        print(f"Chỉ tìm được {len(onsets)}/{args.count} onset.")

    F = features(y)
    pre_f, L = int(args.pre * SR / HOP), int((args.pre + args.length) * SR / HOP)
    starts = [i - pre_f for i in onsets if i - pre_f >= SHIFT and i - pre_f + L + SHIFT <= F.shape[1]]
    template = np.median(np.stack([F[:, s:s + L] for s in starts]), axis=0)
    # onset theo năng lượng lệch vài khung so với đỉnh delta: căn từng đoạn theo mẫu sơ bộ rồi lấy lại
    for _ in range(2):
        aligned = []
        for s in starts:
            s_ncc = ncc(F[:, s - SHIFT:s + L + SHIFT], template)
            aligned.append(s - SHIFT + int(np.argmax(s_ncc)))
        starts = aligned
        template = np.median(np.stack([F[:, s:s + L] for s in starts]), axis=0)
    template = template.astype(np.float32)
    onsets = [s + pre_f for s in starts]
    clips = [F[:, s:s + L] for s in starts]

    print("NCC từng đoạn với mẫu:")
    for i, c in zip(onsets, clips):
        print(f"  {i * HOP / SR:7.2f}s  {ncc(c, template)[0]:.3f}")

    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    out = os.path.join(TEMPLATES_DIR, f"{args.name}.npz")
    np.savez(out, template=template, pre=args.pre, length=args.length, sr=SR, hop=HOP)
    print(f"Đã lưu {out}  (shape {template.shape})")


if __name__ == "__main__":
    main()
