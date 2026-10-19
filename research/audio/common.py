"""Dùng chung cho bài đo âm thanh: đọc WAV, log-mel spectrogram, so khớp mẫu (NCC)."""
import os

import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve, resample_poly, stft

SR = 48000
N_FFT = 2048
HOP = 480  # 10 ms mỗi khung spectrogram
N_MELS = 64
FMIN, FMAX = 100, 12000
MIN_STD = 0.1  # độ lệch chuẩn log-mel tối thiểu của một cửa sổ để NCC có nghĩa

HERE = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(HERE, "sessions")
TEMPLATES_DIR = os.path.join(HERE, "templates")


def hz_to_mel(f):
    return 2595 * np.log10(1 + np.asarray(f, dtype=float) / 700)


def mel_to_hz(m):
    return 700 * (10 ** (np.asarray(m, dtype=float) / 2595) - 1)


def mel_filterbank(sr=SR, n_fft=N_FFT, n_mels=N_MELS, fmin=FMIN, fmax=FMAX):
    freqs = np.linspace(0, sr / 2, n_fft // 2 + 1)
    edges = mel_to_hz(np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2))
    fb = np.zeros((n_mels, len(freqs)), dtype=np.float32)
    for i in range(n_mels):
        lo, mid, hi = edges[i:i + 3]
        fb[i] = np.maximum(0, np.minimum((freqs - lo) / (mid - lo), (hi - freqs) / (hi - mid)))
    return fb


_FB = None


def logmel(y):
    """(N_MELS, T) log-mel của tín hiệu mono float32 ở SR. Khung t bắt đầu tại t*HOP/SR giây."""
    global _FB
    if _FB is None:
        _FB = mel_filterbank()
    _, _, z = stft(y, fs=SR, nperseg=N_FFT, noverlap=N_FFT - HOP, boundary=None, padded=False)
    power = (np.abs(z) ** 2).astype(np.float32)
    return np.log10(_FB @ power + 1e-10)


DELTA_FRAMES = 3  # 30 ms


def features(y):
    """(N_MELS, T) đặc trưng để so khớp: thay đổi của log-mel so với DELTA_FRAMES khung trước.
    Nhấn mạnh phần tấn công của âm thanh, bỏ phần nền ổn định (đo được biên gấp 3 lần log-mel thô)."""
    X = logmel(y)
    d = np.zeros_like(X)
    d[:, DELTA_FRAMES:] = X[:, DELTA_FRAMES:] - X[:, :-DELTA_FRAMES]
    return d


def frame_time(index):
    return index * HOP / SR


def load_wav(path):
    """Mono float32 ở SR (trộn các kênh, resample nếu cần)."""
    sr, data = wavfile.read(path)
    if data.dtype == np.int16:
        y = data.astype(np.float32) / 32768
    elif data.dtype == np.int32:
        y = data.astype(np.float32) / 2147483648
    else:
        y = data.astype(np.float32)
    if y.ndim == 2:
        y = y.mean(axis=1)
    if sr != SR:
        y = resample_poly(y, SR, sr).astype(np.float32)
    return y


def ncc(X, W):
    """Normalized cross-correlation của mẫu W (B, L) trượt theo thời gian trên X (B, T).
    Trả về mảng (T - L + 1,) trong [-1, 1]; điểm t ứng với cửa sổ X[:, t:t+L]."""
    B, L = W.shape
    W = W - W.mean()
    W = W / (np.linalg.norm(W) + 1e-9)
    n = B * L
    num = fftconvolve(X, W[::-1, ::-1].astype(np.float32), mode="valid")[0].astype(np.float64)
    # tổng và tổng bình phương trong cửa sổ bằng cumsum float64 (fftconvolve float32 làm tròn
    # khiến phương sai ở đoạn im lặng âm hoặc ~0 -> NCC bùng nổ)
    col = X.astype(np.float64).sum(axis=0)
    col2 = (X.astype(np.float64) ** 2).sum(axis=0)
    c1 = np.concatenate([[0], np.cumsum(col)])
    c2 = np.concatenate([[0], np.cumsum(col2)])
    s1 = c1[L:] - c1[:-L]
    s2 = c2[L:] - c2[:-L]
    var = s2 - s1 * s1 / n
    # cửa sổ gần như phẳng (im lặng) không được tính là khớp: sàn độ lệch chuẩn 0.1 (1 dB)
    denom = np.sqrt(np.maximum(var, n * MIN_STD ** 2))
    return num / denom


def load_template(path):
    data = np.load(path)
    return data["template"], float(data["pre"]), float(data["length"])
