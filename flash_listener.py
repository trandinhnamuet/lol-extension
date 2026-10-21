"""Nghe tiếng phép bổ trợ (Flash, Thiêu Đốt...) từ âm thanh hệ thống bằng các mô hình CNN nhỏ (ONNX)
chạy trên cùng một log-mel.

    listener = FlashListener(on_event=lambda t, p, spell: ..., threshold=0.95,
                             models={"flash": path1, "ignite": path2}, thresholds={"ignite": 0.95})
    listener.start()      # luồng nền; on_event(t_monotonic, xác suất, tên phép) gọi từ luồng nền
    listener.stop()

Cách làm (giống research/audio/train_cnn.py, phải giữ đúng tham số để mô hình còn đúng):
- Loopback WASAPI (pyaudiowpatch) -> mono float32 48 kHz vào ring buffer, mỗi mẫu có mốc thời
  gian monotonic (đếm theo số mẫu đã ghi; loopback im lặng không trả dữ liệu thì chèn số 0).
- Mỗi 100 ms: log-mel (n_fft 2048, hop 480 = 10 ms, 64 băng mel 100–12000 Hz, log10) của 1,03 s
  cuối -> chuẩn hóa từng băng theo trung vị / IQR chạy -> 2 kênh (log-mel, delta 30 ms) -> ONNX.
- Xác suất theo thời gian; đỉnh >= threshold và cách đỉnh trước >= 1 s -> sự kiện. Mốc sự kiện =
  giữa cửa sổ 1 s (tiếng Flash nằm quanh đó, HUD tối đi ~0,35 s sau).

Chuẩn hóa: lúc huấn luyện dùng trung vị / IQR của cả trận; ở đây dùng thống kê của tối đa 120 s
log-mel gần nhất, cập nhật mỗi 2 s, tối thiểu 3 s đầu rồi mới chấm.
"""
import os
import sys
import threading
import time
from collections import deque

import numpy as np

SR = 48000
N_FFT = 2048
HOP = 480
N_MELS = 64
FMIN, FMAX = 100, 12000
W = 100  # khung = 1 s
DELTA = 3
STEP = 0.1  # giây giữa hai lần chấm
STATS_SECONDS = 120
WARMUP_SECONDS = 3
MIN_GAP = 1.0  # giây giữa hai sự kiện
MAX_GAP_FILL = 0.1  # loopback im lặng: chèn số 0 nếu thiếu hơn chừng này

HERE = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
# exe (PyInstaller --onefile): mô hình được giải nén vào sys._MEIPASS; file cạnh exe (nếu có) ưu tiên
def model_path(name):
    cands = [os.path.join(HERE, "models", name + ".onnx"),
             os.path.join(getattr(sys, "_MEIPASS", HERE), "models", name + ".onnx")]
    return next((p for p in cands if os.path.exists(p)), cands[0])


MODEL_PATH = model_path("flash_cnn")
DEFAULT_MODELS = {"flash": model_path("flash_cnn"), "ignite": model_path("ignite_cnn")}


# ---------- đặc trưng (bản numpy, không cần scipy) ----------
def _hz_to_mel(f):
    return 2595 * np.log10(1 + np.asarray(f, dtype=float) / 700)


def _mel_to_hz(m):
    return 700 * (10 ** (np.asarray(m, dtype=float) / 2595) - 1)


def mel_filterbank():
    freqs = np.linspace(0, SR / 2, N_FFT // 2 + 1)
    edges = _mel_to_hz(np.linspace(_hz_to_mel(FMIN), _hz_to_mel(FMAX), N_MELS + 2))
    fb = np.zeros((N_MELS, len(freqs)), dtype=np.float32)
    for i in range(N_MELS):
        lo, mid, hi = edges[i:i + 3]
        fb[i] = np.maximum(0, np.minimum((freqs - lo) / (mid - lo), (hi - freqs) / (hi - mid)))
    return fb


_FB = None
_WINDOW = None


def logmel(y):
    """(64, T) log-mel của mono float32 48 kHz; giống scipy.signal.stft(boundary=None, padded=False)
    với cửa sổ Hann và chuẩn hóa 1/sum(window) (scipy mặc định scaling='spectrum')."""
    global _FB, _WINDOW
    if _FB is None:
        _FB = mel_filterbank()
        _WINDOW = np.hanning(N_FFT + 1)[:-1].astype(np.float32)  # Hann tuần hoàn như scipy
    n = (len(y) - N_FFT) // HOP + 1
    if n <= 0:
        return np.zeros((N_MELS, 0), np.float32)
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = y[idx] * _WINDOW
    spec = np.fft.rfft(frames, axis=1) / _WINDOW.sum()
    power = (np.abs(spec) ** 2).astype(np.float32)
    return np.log10(power @ _FB.T + 1e-10).T.astype(np.float32)


def with_delta(w):
    d = np.zeros_like(w)
    d[:, DELTA:] = w[:, DELTA:] - w[:, :-DELTA]
    return np.stack([w, d])


class RunningStats:
    """Trung vị / IQR từng băng trên tối đa STATS_SECONDS log-mel gần nhất."""

    def __init__(self):
        self.frames = deque(maxlen=STATS_SECONDS * 100)
        self.med = None
        self.iqr = None
        self.n_at_update = 0

    def push(self, X):
        for col in X.T:
            self.frames.append(col)

    def ready(self):
        return len(self.frames) >= WARMUP_SECONDS * 100

    def update(self):
        if len(self.frames) == self.n_at_update:
            return
        self.n_at_update = len(self.frames)
        a = np.stack(self.frames)  # (T, 64)
        q25, q50, q75 = np.percentile(a, [25, 50, 75], axis=0)
        self.med = q50[:, None].astype(np.float32)
        self.iqr = (q75 - q25 + 1e-3)[:, None].astype(np.float32)

    def normalize(self, X):
        return (X - self.med) / self.iqr


class FlashListener(threading.Thread):
    def __init__(self, on_event, threshold=0.95, model_path=MODEL_PATH, device_index=None,
                 models=None, thresholds=None):
        super().__init__(daemon=True)
        self.on_event = on_event
        self.threshold = threshold
        self.model_path = model_path
        # tên phép -> đường dẫn ONNX; mặc định chỉ Flash (giữ tương thích). Thiếu file thì bỏ qua phép đó.
        self.models = {k: v for k, v in (models or {"flash": model_path}).items() if os.path.exists(v)}
        self.thresholds = dict(thresholds or {})
        self.device_index = device_index
        self.stop_flag = threading.Event()
        self.status = "chưa chạy"
        self.device_name = None
        self.rate = SR
        self.lock = threading.Lock()
        self.buf = np.zeros(SR * 8, np.float32)  # ring 8 s
        self.written = 0  # tổng số mẫu đã ghi (48 kHz)
        self.t0 = None  # monotonic ứng với mẫu 0
        self.probs = {k: deque(maxlen=50) for k in self.models}  # phép -> (t_center, p)
        self.last_event = {k: -1e9 for k in self.models}
        self.session = None
        self.stats = RunningStats()
        self.last_stats_update = 0

    # ---------- âm thanh ----------
    def _open_stream(self):
        import pyaudiowpatch as pa
        self.pa = pa.PyAudio()
        dev = self.pa.get_device_info_by_index(self.device_index) if self.device_index is not None \
            else self.pa.get_default_wasapi_loopback()
        self.device_name = dev["name"]
        self.rate = int(dev["defaultSampleRate"])
        self.channels = dev["maxInputChannels"]
        self.t0 = time.monotonic()
        self.stream = self.pa.open(format=pa.paInt16, channels=self.channels, rate=self.rate, input=True,
                                   input_device_index=dev["index"], frames_per_buffer=1024,
                                   stream_callback=self._callback)

    def _resample(self, y):
        if self.rate == SR:
            return y
        n = int(round(len(y) * SR / self.rate))
        return np.interp(np.linspace(0, len(y), n, endpoint=False), np.arange(len(y)), y).astype(np.float32)

    def _write(self, y):
        n = len(y)
        pos = self.written % len(self.buf)
        end = pos + n
        if end <= len(self.buf):
            self.buf[pos:end] = y
        else:
            k = len(self.buf) - pos
            self.buf[pos:] = y[:k]
            self.buf[:n - k] = y[k:]
        self.written += n

    def _callback(self, data, frame_count, time_info, status):
        import pyaudiowpatch as pa
        try:
            y = np.frombuffer(data, np.int16).astype(np.float32) / 32768
            if self.channels > 1:
                y = y.reshape(-1, self.channels).mean(axis=1)
            y = self._resample(y)
            with self.lock:
                expected = int((time.monotonic() - self.t0) * SR)
                missing = expected - (self.written + len(y))
                if missing > MAX_GAP_FILL * SR:
                    self._write(np.zeros(missing, np.float32))
                self._write(y)
        except Exception as e:  # không để lỗi giết luồng âm thanh
            self.status = f"lỗi âm thanh: {e}"
        return None, pa.paContinue

    def _last(self, n):
        """n mẫu cuối (bản sao) và mốc monotonic của mẫu cuối."""
        with self.lock:
            if self.written < n:
                return None, None
            pos = self.written % len(self.buf)
            if pos >= n:
                y = self.buf[pos - n:pos].copy()
            else:
                y = np.concatenate([self.buf[len(self.buf) - (n - pos):], self.buf[:pos]])
            return y, self.t0 + self.written / SR

    # ---------- mô hình ----------
    def _load_model(self):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.inter_op_num_threads = 1
        self.sessions = {}
        for name, path in self.models.items():
            sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
            self.sessions[name] = (sess, sess.get_inputs()[0].name)
        if not self.sessions:
            raise FileNotFoundError("không có mô hình ONNX nào")

    def score_window(self, X):
        """X: (64, >= W + DELTA) log-mel đã chuẩn hóa; {phép: xác suất} cho cửa sổ W khung cuối."""
        x = with_delta(X[:, -(W + DELTA):])[:, :, DELTA:][None].astype(np.float32)  # (1, 2, 64, W)
        out = {}
        for name, (sess, inp) in self.sessions.items():
            logit = sess.run(None, {inp: x})[0]
            out[name] = float(1 / (1 + np.exp(-logit.reshape(-1)[0])))
        return out

    # ---------- vòng chính ----------
    def run(self):
        try:
            self._load_model()
            self._open_stream()
            self.status = "đang nghe"
        except Exception as e:
            self.status = f"không nghe được: {e}"
            return
        need = N_FFT + HOP * (W + DELTA - 1)  # mẫu cho W + DELTA khung
        next_at = time.monotonic()
        try:
            while not self.stop_flag.is_set():
                next_at += STEP
                time.sleep(max(0, next_at - time.monotonic()))
                y, t_end = self._last(need)
                if y is None:
                    continue
                X = logmel(y)  # (64, W + DELTA)
                self.stats.push(X[:, -10:])  # 10 khung mới (100 ms)
                if not self.stats.ready():
                    continue
                if t_end - self.last_stats_update >= 2:
                    self.stats.update()
                    self.last_stats_update = t_end
                p = self.score_window(self.stats.normalize(X))
                t_center = t_end - 0.5
                for name, v in p.items():
                    self.probs[name].append((t_center, v))
                    self._maybe_emit(name)
        except Exception as e:
            self.status = f"lỗi: {e}"
        finally:
            try:
                self.stream.stop_stream()
                self.stream.close()
                self.pa.terminate()
            except Exception:
                pass
            if self.status == "đang nghe":
                self.status = "đã dừng"

    def _maybe_emit(self, name="flash"):
        """Đỉnh: p[-2] >= ngưỡng, lớn hơn hai bên, cách sự kiện trước (cùng phép) >= MIN_GAP."""
        probs = self.probs[name]
        if len(probs) < 3:
            return
        (t1, p1), (t2, p2), (t3, p3) = probs[-3], probs[-2], probs[-1]
        thr = self.thresholds.get(name, self.threshold)
        if p2 >= thr and p2 >= p1 and p2 >= p3 and t2 - self.last_event[name] >= MIN_GAP:
            self.last_event[name] = t2
            try:
                self.on_event(t2, p2, name)
            except Exception as e:
                self.status = f"lỗi on_event: {e}"

    def stop(self):
        self.stop_flag.set()


if __name__ == "__main__":  # chạy thử: in ra mỗi lần nghe thấy phép
    def show(t, p, spell):
        print(f"\n{spell.upper()}  p={p:.2f}  t={t:.2f}", flush=True)

    lst = FlashListener(show, threshold=float(sys.argv[1]) if len(sys.argv) > 1 else 0.9, models=DEFAULT_MODELS)
    lst.start()
    try:
        while True:
            time.sleep(1)
            last = " ".join(f"{k}={v[-1][1]:.2f}" for k, v in lst.probs.items() if v)
            print(f"\r{lst.status} | {lst.device_name} | {last}   ", end="", flush=True)
    except KeyboardInterrupt:
        lst.stop()
