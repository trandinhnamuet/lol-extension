"""Xuất models/flash_cnn.pt (PyTorch) sang <gốc project>/models/flash_cnn.onnx cho app, rồi kiểm
onnxruntime cho cùng kết quả với PyTorch trên một phiên.

    python research/audio/export_onnx.py [--check sessions/replay_<x>]
"""
import argparse
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_cnn import FlashCNN, W, with_delta  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(HERE, "models", "flash_cnn.pt")
DST = os.path.join(ROOT, "models", "flash_cnn.onnx")  # --name ignite_cnn -> ignite_cnn.pt / .onnx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", help="phiên có logmel.npy để so sánh")
    ap.add_argument("--name", default="flash_cnn")
    args = ap.parse_args()
    global SRC, DST
    SRC, DST = os.path.join(HERE, "models", args.name + ".pt"), os.path.join(ROOT, "models", args.name + ".onnx")
    model = FlashCNN()
    model.load_state_dict(torch.load(SRC, map_location="cpu", weights_only=True))
    model.eval()
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    dummy = torch.zeros(1, 2, 64, W)
    torch.onnx.export(model, dummy, DST, input_names=["x"], output_names=["logit"],
                      dynamic_axes={"x": {0: "batch"}, "logit": {0: "batch"}}, opset_version=17)
    print("Đã xuất", DST, os.path.getsize(DST), "bytes")

    import onnxruntime as ort
    sess = ort.InferenceSession(DST, providers=["CPUExecutionProvider"])
    if args.check:
        X = np.load(os.path.join(args.check, "logmel.npy"))
        med = np.median(X, axis=1, keepdims=True)
        iqr = np.percentile(X, 75, axis=1, keepdims=True) - np.percentile(X, 25, axis=1, keepdims=True) + 1e-3
        X = ((X - med) / iqr).astype(np.float32)
        starts = np.random.default_rng(0).integers(0, X.shape[1] - W, 200)
        xb = np.stack([with_delta(X[:, s:s + W]) for s in starts]).astype(np.float32)
    else:
        xb = np.random.randn(200, 2, 64, W).astype(np.float32)
    with torch.no_grad():
        ref = model(torch.from_numpy(xb)).numpy()
    out = sess.run(None, {"x": xb})[0].reshape(-1)
    print(f"Sai lệch logit lớn nhất torch vs onnx: {np.abs(ref - out).max():.5f}")


if __name__ == "__main__":
    main()
