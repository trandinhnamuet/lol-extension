"""Kiểm luật quy kết Thiêu Đốt bằng ảnh toàn màn hình đã ghi (phiên có frames/ 960×540, 4 fps), không cần game.

    python research/audio/test_ignite_offline.py sessions/replay_1609077581_20261019_204709 [--team CHAOS]

Với mỗi mốc Thiêu Đốt của phe "địch" (theo góc nhìn app: --team), lấy các khung trong [t − 1, t + 1],
chạy minimap_tracker trên vùng minimap của khung (tỉ lệ 540p: vòng bán kính ~5–7 px), rồi áp luật:
ứng viên = địch mang Thiêu Đốt còn phép, cách một vòng xanh ≤ 600 × 1,3 đơn vị. In đúng / sai / hỏi.
Cũng đếm mốc Thiêu Đốt của phe kia (đồng minh) mà luật sẽ gán nhầm cho địch (bấm không căn cứ).
"""
import argparse
import csv
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import minimap_tracker as mt  # noqa: E402

RECT_540 = (828, 405, 132, 135)  # minimap trong khung 960×540
CACHE = os.path.join(ROOT, "cache", "champion")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--team", default="CHAOS", help="phe địch theo app")
    ap.add_argument("--slack", type=float, default=1.3)
    args = ap.parse_args()
    s = args.session
    data = json.load(open(os.path.join(s, "allgamedata.json"), encoding="utf-8"))
    cid = {p["championName"]: (p.get("rawChampionName", "").rsplit("_", 1)[-1] or p["championName"]) for p in data["allPlayers"]}
    carries = {cid[p["championName"]] for p in data["allPlayers"]
               if any("SummonerDot" in p["summonerSpells"][k]["rawDisplayName"] for k in ("summonerSpellOne", "summonerSpellTwo"))}
    enemies = [cid[p["championName"]] for p in data["allPlayers"] if p["team"] == args.team]
    allies = [cid[p["championName"]] for p in data["allPlayers"] if p["team"] != args.team]
    ally_carriers = [c for c in allies if c in carries]
    frames = list(csv.DictReader(open(os.path.join(s, "frames.csv"))))
    ft = np.array([float(r["t"]) for r in frames])
    events = [(float(e["t"]), cid.get(e["champion"], e["champion"]), e["team"])
              for e in csv.DictReader(open(os.path.join(s, "ignite_events.csv"), encoding="utf-8"))]
    tr = mt.MinimapTracker(rect=RECT_540)
    tr.set_enemies({c: os.path.join(CACHE, c + ".png") for c in enemies})
    tr.set_allies({c: os.path.join(CACHE, c + ".png") for c in allies})
    radius = tr.units_to_px(600) * args.slack
    print(f"địch {enemies} (mang Thiêu Đốt: {[c for c in enemies if c in carries]}), đồng minh mang: {ally_carriers}; tầm {radius:.1f} px")
    ok = wrong = ask = unfounded = skip = 0
    for t, champ, team in sorted(events):
        for c in list(tr.history):
            tr.history[c].clear()
        for c in list(tr.ally_history):
            tr.ally_history[c].clear()
        tr.blue_positions.clear()
        idx = np.flatnonzero((ft >= t - 1.0) & (ft <= t + 1.0))
        x, y, w, h = RECT_540
        for i in idx:
            img = cv2.imread(os.path.join(s, "frames", frames[i]["file"]))
            if img is None:
                continue
            tr.process(np.ascontiguousarray(img[y:y + h, x:x + w]), float(ft[i]))
        t0, t1 = t - 0.8, t + 0.5
        near = []
        for c in enemies:
            if c not in carries:
                continue
            pos = tr.position(c, t0, t1)
            if pos and tr.allies_near(pos[0], pos[1], radius, t0, t1):
                near.append(c)
        ambiguous = False
        for c in near:
            pos = tr.position(c, t0, t1)
            for a in ally_carriers:
                ap_ = tr.position(a, t0, t1, ally=True)
                if ap_ and np.hypot(ap_[0] - pos[0], ap_[1] - pos[1]) <= radius:
                    ambiguous = True
        verdict = "hỏi"
        if len(near) == 1 and not ambiguous:
            verdict = "TỰ BẤM " + near[0]
        is_enemy = team == args.team
        label = f"{int(t)//60}:{int(t)%60:02d} {'địch' if is_enemy else 'đồng minh':9s} {champ:12s} ứng viên={near}{' (mơ hồ)' if ambiguous else ''} -> {verdict}"
        if is_enemy:
            if verdict.startswith("TỰ BẤM"):
                if near[0] == champ:
                    ok += 1
                else:
                    wrong += 1
                    label += "  SAI"
            else:
                ask += 1
        else:
            if verdict.startswith("TỰ BẤM"):
                unfounded += 1
                label += "  KHÔNG CĂN CỨ"
            else:
                skip += 1
        print(label)
    n_enemy = sum(1 for _, _, tm in events if tm == args.team)
    print(f"\nThiêu Đốt địch: {n_enemy} | tự bấm đúng {ok} | sai {wrong} | hỏi {ask}")
    print(f"Thiêu Đốt đồng minh: {len(events) - n_enemy} | bấm không căn cứ {unfounded} | hỏi/bỏ qua {skip}")


if __name__ == "__main__":
    main()
