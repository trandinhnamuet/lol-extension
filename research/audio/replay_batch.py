"""Chạy hàng loạt: với mỗi gameId, tải + mở replay + ghi (âm thanh, HUD, giờ game) tới hết trận,
rồi lấy mốc Flash từ HUD. Tùy chọn thêm lượt lấy vị trí. Bỏ qua trận đã có phiên replay_<gameId>_*.

    python replay_batch.py 1608862888 1608842566 ...        # ghi lần lượt
    python replay_batch.py --from-history --min-minutes 15  # mọi trận CLASSIC cùng patch trong lịch sử
    python replay_batch.py ... --positions                   # thêm lượt vị trí (gấp đôi thời gian)

Mỗi trận tốn ~ thời lượng trận + 1,5 phút. Nhật ký: sessions/batch.log. Tạo file sessions/BATCH_STOP
để dừng sau trận hiện tại. Cần client đang đăng nhập; đừng click sang cửa sổ khác lúc ghi.
"""
import argparse
import glob
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SESSIONS_DIR  # noqa: E402
from replay_session import LCU  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    with open(os.path.join(SESSIONS_DIR, "batch.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def from_history(lcu, min_minutes):
    st, d = lcu("GET", "/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=60")
    st2, cfg = lcu("GET", "/lol-replays/v1/configuration")
    patch = ".".join(cfg["gameVersion"].split(".")[:2])
    ids = []
    for g in d["games"]["games"]:
        if g["gameMode"] == "CLASSIC" and g["gameVersion"].startswith(patch + ".") \
                and g["gameDuration"] >= min_minutes * 60:
            ids.append(g["gameId"])
    return ids


def audio_check(session, n=20):
    """Game mất focus thì tắt tiếng: đếm đoạn 1 s gần im lặng trong n đoạn rải đều của audio.wav."""
    import wave
    import numpy as np
    try:
        f = wave.open(os.path.join(session, "audio.wav"))
        frames, rate = f.getnframes(), f.getframerate()
        quiet = 0
        for k in range(n):
            f.setpos(int(frames * (k + 0.5) / n))
            a = np.frombuffer(f.readframes(rate), np.int16).astype(float) / 32768
            quiet += 20 * np.log10(np.sqrt((a ** 2).mean()) + 1e-9) < -45
        f.close()
        if quiet:
            log(f"    CẢNH BÁO: {quiet}/{n} đoạn gần im lặng (< -45 dB), có thể game mất focus; nên ghi lại")
        else:
            log(f"    âm thanh ổn: 0/{n} đoạn im lặng")
        return quiet
    except Exception as e:
        log(f"    không kiểm tra được âm thanh: {e}")
        return -1


def run(args, label, timeout):
    log(f"  > {label}")
    r = subprocess.run([PY, "-u", *args], cwd=HERE, timeout=timeout,
                       env={**os.environ, "PYTHONUTF8": "1"}, capture_output=True, text=True)
    tail = (r.stdout or "").replace("\r", "\n").strip().splitlines()[-3:]
    for t in tail:
        log("    " + t)
    if r.returncode:
        log(f"    lỗi {r.returncode}: {(r.stderr or '').strip().splitlines()[-1:]}")
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_ids", nargs="*", type=int)
    ap.add_argument("--from-history", action="store_true")
    ap.add_argument("--min-minutes", type=int, default=15)
    ap.add_argument("--positions", action="store_true")
    ap.add_argument("--full-frames", action="store_true", help="lưu cả khung hình thay vì chỉ HUD")
    args = ap.parse_args()

    lcu = LCU()
    ids = list(args.game_ids)
    if args.from_history:
        ids += [g for g in from_history(lcu, args.min_minutes) if g not in ids]
    todo = [g for g in ids if not glob.glob(os.path.join(SESSIONS_DIR, f"replay_{g}_*", "flash_events.csv"))]
    log(f"Bắt đầu: {len(todo)} trận ({len(ids) - len(todo)} đã có): {todo}")
    stop_file = os.path.join(SESSIONS_DIR, "BATCH_STOP")
    for n, g in enumerate(todo, 1):
        if os.path.exists(stop_file):
            log("Có BATCH_STOP, dừng.")
            break
        log(f"[{n}/{len(todo)}] trận {g}")
        before = set(glob.glob(os.path.join(SESSIONS_DIR, f"replay_{g}_*")))
        ok = run(["replay_session.py", str(g), "--kill"] + ([] if args.full_frames else ["--hud-only"]),
                 "ghi replay", timeout=5400)
        new = [p for p in glob.glob(os.path.join(SESSIONS_DIR, f"replay_{g}_*")) if p not in before]
        if not ok or not new:
            log("  bỏ qua trận này")
            subprocess.run(["taskkill", "/IM", "League of Legends.exe", "/F"], capture_output=True)
            time.sleep(10)
            continue
        session = new[-1]
        audio_check(session)
        run(["hud_flash.py", session], "mốc Flash từ HUD", timeout=1800)
        if args.positions:
            time.sleep(10)
            run(["replay_positions.py", str(g), "--speed", "2", "--kill"], "vị trí 10 tướng", timeout=5400)
        time.sleep(10)
    log("Xong hàng loạt.")


if __name__ == "__main__":
    main()
