"""Chạy lại logic quy kết trên các dòng "vết:" trong auto_flash.log (không cần game), với tham số
who_jumped hiện tại của minimap_tracker.py, và chấm theo HUD. Dùng để chỉnh ngưỡng nhảy / cửa sổ
thời gian mà không phải chạy lại replay.

    python research/audio/replay_auto_log.py <auto_flash.log> sessions/replay_<x> --team CHAOS
    python research/audio/replay_auto_log.py ... --before 0.5 --after 0.3   # thử cửa sổ khác

Với mỗi tiếng: ứng viên theo tham số mới -> tự bấm (đúng/sai) / hỏi; đối chiếu HUD như
compare_auto_log.py. Cũng in độ lệch thời gian giữa mốc tiếng và cú nhảy ở các lần đúng.
"""
import argparse
import ast
import csv
import json
import os
import re
import sys
from collections import deque

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import minimap_tracker as mt  # noqa: E402


def parse(path):
    events = []  # (mono, gt, p, tracks)
    pending = None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\S+ mono=([\d.]+) game=(\d+):(\d+) (.*)", line.rstrip("\n"))
        if not m:
            continue
        mono, gt, msg = float(m.group(1)), int(m.group(2)) * 60 + int(m.group(3)), m.group(4)
        if msg.startswith("vết:"):
            tracks = {}
            for part in msg[4:].split(";"):
                part = part.strip()
                if "=" in part:
                    c, v = part.split("=", 1)
                    try:
                        tracks[c.strip()] = ast.literal_eval(v)
                    except Exception:
                        pass
            pending = (mono, gt, tracks)
        elif msg.startswith("tiếng p="):
            p = float(re.search(r"p=([\d.]+)", msg).group(1))
            tracks = pending[2] if pending and abs(pending[0] - mono) < 1 else {}
            events.append((mono, gt, p, tracks))
            pending = None
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("session")
    ap.add_argument("--team", required=True)
    ap.add_argument("--before", type=float)
    ap.add_argument("--after", type=float)
    ap.add_argument("--tol", type=float, default=2.5)
    args = ap.parse_args()
    if args.before is not None:
        mt.WINDOW_BEFORE = args.before
    if args.after is not None:
        mt.WINDOW_AFTER = args.after
    data = json.load(open(os.path.join(args.session, "allgamedata.json"), encoding="utf-8"))
    champ_of = {p["championName"]: (p.get("rawChampionName", "").rsplit("_", 1)[-1] or p["championName"])
                for p in data["allPlayers"]}
    ev = [(float(e["gameTime"]), champ_of.get(e["champion"], e["champion"]))
          for e in csv.DictReader(open(os.path.join(args.session, "flash_events.csv"), encoding="utf-8"))
          if e["team"] == args.team]
    events = parse(args.log)
    tr = mt.MinimapTracker(rect=(0, 0, 264, 270))
    tr.start = lambda: None
    ok = wrong = ask = unfounded = 0
    offsets = []
    for mono, gt, p, tracks in events:
        tr.history = {c: deque((mono + dt, x, y, s) for dt, x, y, s in v) for c, v in tracks.items()}
        jumped = tr.who_jumped(mono)
        truth = [c for g, c in ev if abs(g - gt) <= args.tol]
        if len(jumped) == 1:
            who = jumped[0][0]
            if who in truth:
                ok += 1
                # thời điểm cú nhảy so với mốc tiếng
                pts = sorted(tr.history[who])
                for (t1, x1, y1, _), (t2, x2, y2, _) in zip(pts, pts[1:]):
                    if np.hypot(x2 - x1, y2 - y1) >= 264 * mt.JUMP_PX_FRAC and 0 < t2 - t1 <= mt.JUMP_MAX_DT:
                        offsets.append(round(t2 - mono, 2))
            elif truth:
                wrong += 1
                print(f"  {gt//60}:{gt%60:02d} bấm {who} nhưng HUD: {truth}")
            else:
                unfounded += 1
                print(f"  {gt//60}:{gt%60:02d} bấm {who} nhưng HUD không có Flash địch")
        else:
            ask += 1
    heard_truth = sum(1 for g, c in ev if any(abs(g - gt) <= args.tol for _, gt, _, _ in events))
    print(f"\nTham số: nhảy {264*mt.JUMP_PX_FRAC:.1f}-{264*mt.JUMP_MAX_FRAC:.1f} px, cửa sổ [-{mt.WINDOW_BEFORE}, +{mt.WINDOW_AFTER}] s")
    print(f"HUD Flash địch: {len(ev)}, trong đó app nghe thấy {heard_truth}. Tiếng: {len(events)}")
    print(f"Tự bấm đúng {ok} | bấm sai {wrong} | không căn cứ {unfounded} | hỏi {ask}")
    if offsets:
        print("Lệch cú nhảy - mốc tiếng (s) ở các lần đúng:", sorted(offsets))


if __name__ == "__main__":
    main()
