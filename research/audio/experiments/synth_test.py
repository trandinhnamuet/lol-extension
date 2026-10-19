"""Kiểm tra make_template + detect bằng WAV tổng hợp: 8 'tiếng Flash' giả (chirp + nhiễu
có màu) đặt ở các mốc đã biết, trên nền nhiễu + vài tiếng khác. Chạy từ thư mục gốc project."""
import os
import subprocess
import sys

import numpy as np
from scipy.io import wavfile

SR = 48000
rng = np.random.default_rng(0)
out = os.path.join(sys.argv[1], "synth")
os.makedirs(out, exist_ok=True)


def flash_sound():
    t = np.arange(int(0.4 * SR)) / SR
    env = np.exp(-t * 8)
    chirp = np.sin(2 * np.pi * (600 * t + 2500 * t ** 2))
    noise = rng.standard_normal(len(t)) * 0.3
    return (chirp + noise) * env


def other_sound(f):
    t = np.arange(int(0.3 * SR)) / SR
    return np.sin(2 * np.pi * f * t) * np.exp(-t * 10)


# bản ghi yên tĩnh: 8 Flash cách 3 s
quiet = rng.standard_normal(int(30 * SR)) * 0.002
flash_times = [2 + 3 * i for i in range(8)]
for ft in flash_times:
    i = int(ft * SR)
    quiet[i:i + len(flash_sound())] += flash_sound() * 0.5
wavfile.write(os.path.join(out, "quiet.wav"), SR, (quiet * 32767).astype(np.int16))

# bản ghi "trận": nhiễu to hơn, 20 tiếng khác, 6 Flash ở biên độ khác nhau
game = rng.standard_normal(int(120 * SR)) * 0.02
for _ in range(20):
    i = int(rng.uniform(1, 118) * SR)
    s = other_sound(rng.uniform(300, 3000))
    game[i:i + len(s)] += s * 0.5
true_times = [10, 25, 40, 55, 70, 100]
amps = [0.5, 0.3, 0.15, 0.08, 0.5, 0.3]
for ft, a in zip(true_times, amps):
    i = int(ft * SR)
    game[i:i + len(flash_sound())] += flash_sound() * a
wavfile.write(os.path.join(out, "game.wav"), SR, (np.clip(game, -1, 1) * 32767).astype(np.int16))

here = os.path.join("research", "audio")
subprocess.run([sys.executable, os.path.join(here, "make_template.py"), os.path.join(out, "quiet.wav"),
                "--name", "synth_flash", "--count", "8"], check=True)
print("\n=== dò trên game.wav (Flash thật tại", true_times, ") ===")
subprocess.run([sys.executable, os.path.join(here, "detect.py"), os.path.join(out, "game.wav"),
                "--template", "synth_flash", "--thr", "0.3", "--no-images"], check=True)
