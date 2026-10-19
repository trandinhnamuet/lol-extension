"""Ghi một phiên đo: âm thanh loopback (toàn bộ âm thanh hệ thống) + ảnh màn hình thu nhỏ
+ giờ game từ Live Client API. Dừng bằng Ctrl+C.

    python record.py                 # ghi đủ (âm thanh + ảnh + giờ game)
    python record.py --no-screen     # chỉ âm thanh (dùng khi ghi mẫu trong Practice Tool)

Kết quả: sessions/<YYYYmmdd_HHMMSS>/
    audio.wav         stereo int16, đúng tần số thiết bị
    frames/*.jpg      ảnh màn hình 960x540, --fps ảnh/giây
    frames.csv        t,file  (t = giây kể từ lúc bắt đầu ghi)
    game.csv          t,gameTime
    allgamedata.json  dữ liệu trận lúc kết nối được API lần đầu
"""
import argparse
import csv
import json
import os
import ssl
import sys
import threading
import time
import urllib.request
import wave

import numpy as np
import pyaudiowpatch as pa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SESSIONS_DIR  # noqa: E402

API_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
MAX_GAP = 0.1  # giây: loopback im lặng không trả dữ liệu -> chèn số 0 để giữ đúng mốc thời gian


class Recorder:
    def __init__(self, session, fps, monitor, screen, game, seconds=None):
        self.session = session
        self.fps = fps
        self.monitor = monitor
        self.want_screen = screen
        self.want_game = game
        self.seconds = seconds
        self.stop = threading.Event()
        self.t0 = None
        self.gaps = 0
        self.frames_saved = 0
        self.game_rows = 0

    # ---------- âm thanh ----------
    def run_audio(self):
        p = pa.PyAudio()
        dev = p.get_default_wasapi_loopback()
        rate, channels = int(dev["defaultSampleRate"]), dev["maxInputChannels"]
        print(f"Thiết bị: {dev['name']}  {rate} Hz  {channels} kênh")
        wav = wave.open(os.path.join(self.session, "audio.wav"), "wb")
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        written = 0
        lock = threading.Lock()

        def callback(data, frame_count, time_info, status):
            nonlocal written
            with lock:
                expected = int((time.perf_counter() - self.t0) * rate)
                missing = expected - (written + frame_count)
                if missing > MAX_GAP * rate:
                    wav.writeframes(bytes(missing * channels * 2))
                    written += missing
                    self.gaps += 1
                wav.writeframes(data)
                written += frame_count
            return None, pa.paContinue

        self.t0 = time.perf_counter()
        stream = p.open(format=pa.paInt16, channels=channels, rate=rate, input=True,
                        input_device_index=dev["index"], frames_per_buffer=1024,
                        stream_callback=callback)
        try:
            while not self.stop.is_set():
                time.sleep(0.2)
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
            with lock:
                wav.close()
            print(f"Âm thanh: {written / rate:.1f}s, chèn im lặng {self.gaps} lần")

    # ---------- ảnh màn hình ----------
    def run_screen(self):
        import cv2
        import dxcam
        cam = dxcam.create(output_idx=self.monitor, output_color="BGR")
        frames_dir = os.path.join(self.session, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        f = open(os.path.join(self.session, "frames.csv"), "w", newline="")
        writer = csv.writer(f)
        writer.writerow(["t", "file"])
        interval = 1 / self.fps
        next_at = time.perf_counter()
        last = None
        while not self.stop.is_set():
            frame = cam.grab()
            if frame is not None:
                last = frame
            now = time.perf_counter()
            if now >= next_at and last is not None:
                next_at += interval
                small = cv2.resize(last, (960, 540), interpolation=cv2.INTER_AREA)
                name = f"{self.frames_saved:06d}.jpg"
                cv2.imwrite(os.path.join(frames_dir, name), small, [cv2.IMWRITE_JPEG_QUALITY, 80])
                writer.writerow([f"{now - self.t0:.3f}", name])
                self.frames_saved += 1
            else:
                time.sleep(0.005)
        f.close()
        del cam
        print(f"Ảnh: {self.frames_saved} khung")

    # ---------- giờ game ----------
    def run_game(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                             urllib.request.HTTPSHandler(context=ctx))
        f = open(os.path.join(self.session, "game.csv"), "w", newline="")
        writer = csv.writer(f)
        writer.writerow(["t", "gameTime"])
        saved = False
        while not self.stop.is_set():
            try:
                with opener.open(API_URL, timeout=1.5) as r:
                    data = json.loads(r.read().decode("utf-8"))
                t = time.perf_counter() - self.t0
                writer.writerow([f"{t:.3f}", data["gameData"]["gameTime"]])
                f.flush()
                self.game_rows += 1
                if not saved:
                    with open(os.path.join(self.session, "allgamedata.json"), "w",
                              encoding="utf-8") as g:
                        json.dump(data, g, ensure_ascii=False, indent=1)
                    saved = True
                    print("Đã kết nối Live Client API")
            except Exception:
                pass
            self.stop.wait(2)
        f.close()
        print(f"Giờ game: {self.game_rows} mốc")

    def run(self):
        threads = [threading.Thread(target=self.run_audio, daemon=True)]
        self.t0 = time.perf_counter()
        if self.want_screen:
            threads.append(threading.Thread(target=self.run_screen, daemon=True))
        if self.want_game:
            threads.append(threading.Thread(target=self.run_game, daemon=True))
        for t in threads:
            t.start()
        stop_file = os.path.join(self.session, "STOP")
        print(f"Đang ghi vào {self.session}\nBấm Ctrl+C hoặc tạo file {stop_file} để dừng.")
        try:
            while self.seconds is None or time.perf_counter() - self.t0 < self.seconds:
                time.sleep(1)
                if os.path.exists(stop_file):
                    break
                elapsed = time.perf_counter() - self.t0
                print(f"\r{elapsed:7.0f}s  ảnh {self.frames_saved}  giờ game {self.game_rows}  "
                      f"gap {self.gaps}   ", end="", flush=True)
        except KeyboardInterrupt:
            pass
        print("\nĐang dừng...")
        self.stop.set()
        for t in threads:
            t.join(timeout=5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=SESSIONS_DIR)
    ap.add_argument("--fps", type=float, default=4, help="ảnh màn hình mỗi giây")
    ap.add_argument("--monitor", type=int, default=0, help="màn hình đang chạy game")
    ap.add_argument("--no-screen", action="store_true")
    ap.add_argument("--no-game", action="store_true")
    ap.add_argument("--seconds", type=float, help="tự dừng sau chừng này giây")
    args = ap.parse_args()
    session = os.path.join(args.out, time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(session, exist_ok=True)
    Recorder(session, args.fps, args.monitor, not args.no_screen, not args.no_game,
             args.seconds).run()


if __name__ == "__main__":
    main()
