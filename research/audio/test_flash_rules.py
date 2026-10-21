"""Chạy lại luật quy kết Flash trên ảnh minimap thô app đã lưu quanh mỗi tiếng (debug_frames/), không cần game.

    python research/audio/test_flash_rules.py <debug_frames> sessions/replay_<x> [--team CHAOS]

Mỗi thư mục con NNN_flash_g<giây game>: các ảnh minimap tên <dt>.png (dt giây so với mốc tiếng).
Cho mỗi tiếng in: nguồn thật (HUD: địch / đồng minh / không có), cú nhảy vòng xanh, cú nhảy vòng đỏ,
địch có tên nhảy (who_jumped), rồi quyết định theo luật hiện tại của minimap_tracker, và tổng kết:
tự bấm đúng / sai / bỏ qua vì là Flash đồng minh / hỏi.
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import minimap_tracker as mt  # noqa: E402

CACHE = os.path.join(ROOT, "cache", "champion")


def decide(tr, rows_by_champ_ids):
    """Luật quyết định (bản thử): trả (hành động, chi tiết). Dùng chung với auto_flash.decide."""
    jumped = [(c, px) for c, px in tr.who_jumped(0.0) if c in rows_by_champ_ids]
    blue = tr.ring_jumps(0.0, "blue")
    if len(jumped) == 1 and not blue:
        return "TỰ BẤM", jumped[0][0]
    if len(jumped) == 1 and blue:
        return "HỎI", f"{jumped[0][0]} nhưng vòng xanh cũng nhảy"
    if not jumped and blue:
        return "BỎ QUA (Flash đồng minh)", ""
    return "HỎI", ", ".join(c for c, _ in jumped)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("debug")
    ap.add_argument("session")
    ap.add_argument("--team", default="CHAOS")
    ap.add_argument("--tol", type=float, default=3.0)
    ap.add_argument("--fog-lum", type=float, help="bỏ icon địch nằm trong vùng sương mù (độ sáng nền < giá trị này); ảnh phải ghi ở chế độ Xanh")
    args = ap.parse_args()
    data = json.load(open(os.path.join(args.session, "allgamedata.json"), encoding="utf-8"))
    cid = {p["championName"]: (p.get("rawChampionName", "").rsplit("_", 1)[-1] or p["championName"]) for p in data["allPlayers"]}
    enemies = [cid[p["championName"]] for p in data["allPlayers"] if p["team"] == args.team]
    allies = [cid[p["championName"]] for p in data["allPlayers"] if p["team"] != args.team]
    ev = [(float(e["gameTime"]), cid.get(e["champion"], e["champion"]), e["team"])
          for e in csv.DictReader(open(os.path.join(args.session, "flash_events.csv"), encoding="utf-8"))]
    tot = {}
    print(f"địch {enemies}\nđồng minh {allies}\n")
    for d in sorted(glob.glob(os.path.join(args.debug, "*_flash_g*"))):
        g = int(re.search(r"_g(\d+)$", d).group(1))
        near = [e for e in ev if abs(e[0] - g) <= args.tol + 1]
        who = "không Flash HUD" if not near else ("địch" if any(e[2] == args.team for e in near) else "đồng minh")
        true_enemy = [e[1] for e in near if e[2] == args.team]
        tr = mt.MinimapTracker(rect=(0, 0, 264, 270))
        tr.fog_min_lum = args.fog_lum
        tr.set_enemies({c: os.path.join(CACHE, c + ".png") for c in enemies})
        tr.set_allies({c: os.path.join(CACHE, c + ".png") for c in allies})
        files = sorted(glob.glob(os.path.join(d, "*.png")), key=lambda p: float(os.path.basename(p)[:-4]))
        for f in files:
            tr.process(np.ascontiguousarray(cv2.imread(f)), float(os.path.basename(f)[:-4]))
        act, detail = decide(tr, set(enemies))
        blue, red = tr.ring_jumps(0.0, "blue"), tr.ring_jumps(0.0, "red")
        if act == "TỰ BẤM":
            res = "ĐÚNG" if detail in true_enemy else ("SAI" if who != "không Flash HUD" else "KHÔNG CĂN CỨ")
        else:
            res = act
        key = (who, res if act == "TỰ BẤM" else act)
        tot[key] = tot.get(key, 0) + 1
        print(f"{os.path.basename(d):24s} thật={who:15s} {true_enemy!s:22s} xanh={len(blue)} đỏ={len(red)} "
              f"có tên={[c for c, _ in tr.who_jumped(0.0)]} -> {act} {detail} {'['+res+']' if act=='TỰ BẤM' else ''}")
    print("\nTổng kết:")
    for (who, res), n in sorted(tot.items()):
        print(f"  thật={who:15s} {res:28s} {n}")


if __name__ == "__main__":
    main()
