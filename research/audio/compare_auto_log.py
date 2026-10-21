"""Đối chiếu auto_flash.log của app (chạy trong lúc xem replay) với mốc Flash HUD của phiên ghi
cùng lúc (flash_events.csv + allgamedata.json), theo giờ game.

    python research/audio/compare_auto_log.py <auto_flash.log> sessions/replay_<x> [--team CHAOS]

Với mỗi Flash HUD của phe địch (team khác phe người chơi, mặc định suy từ replay.json): app có
nghe thấy không (dòng "tiếng" trong ±2 s giờ game), có tự bấm đúng tướng không, hay hỏi, hay bỏ qua.
Và ngược lại: mỗi lần app TỰ BẤM có trùng Flash HUD của đúng tướng không.
"""
import argparse
import csv
import json
import os
import re

import numpy as np


def parse_log(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        m = re.match(r"(\S+) mono=([\d.]+) game=(\d+):(\d+) (.*)", line.strip())
        if not m:
            continue
        gt = int(m.group(3)) * 60 + int(m.group(4))
        rows.append((float(m.group(2)), gt, m.group(5)))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("session")
    ap.add_argument("--team", help="phe địch theo app (ORDER/CHAOS); mặc định: phe khác người chơi")
    ap.add_argument("--tol", type=float, default=2.5)
    ap.add_argument("--spell", default="flash", help="flash | ignite: đọc <spell>_events.csv và dòng log của phép đó")
    args = ap.parse_args()
    SP = args.spell
    s = args.session
    meta = json.load(open(os.path.join(s, "replay.json"), encoding="utf-8"))
    data = json.load(open(os.path.join(s, "allgamedata.json"), encoding="utf-8"))
    me = meta["me"].split("#")[0]
    my_team = next((p["team"] for p in data["allPlayers"] if p.get("riotIdGameName") == me), "ORDER")
    enemy_team = args.team or ("CHAOS" if my_team == "ORDER" else "ORDER")
    champ_of = {}
    for p in data["allPlayers"]:
        raw = p.get("rawChampionName", "")
        champ_of[p["championName"]] = raw.rsplit("_", 1)[-1] if raw else p["championName"]
    events = [r for r in csv.DictReader(open(os.path.join(s, f"{SP}_events.csv"), encoding="utf-8"))]
    enemy_ev = [(float(e["gameTime"]), champ_of.get(e["champion"], e["champion"]), e["champion"])
                for e in events if e["team"] == enemy_team]
    ally_ev = [(float(e["gameTime"]), e["champion"]) for e in events if e["team"] != enemy_team]
    log = parse_log(args.log)
    # dòng log: "tiếng p=…" (Flash, bản cũ) hoặc "tiếng <phép> p=…"
    heard = [(gt, msg) for _, gt, msg in log
             if msg.startswith(f"tiếng {SP} ") or (SP == "flash" and msg.startswith("tiếng p="))]
    auto = [(gt, re.search(r"TỰ BẤM (\S+)", msg).group(1)) for gt, msg in heard if "TỰ BẤM" in msg]
    asked = [(gt, msg) for gt, msg in heard if "HỎI" in msg]

    print(f"Phe địch theo app: {enemy_team}. HUD: {len(enemy_ev)} Flash địch, {len(ally_ev)} Flash đồng minh/mình.")
    print(f"App: nghe thấy {len(heard)} tiếng, tự bấm {len(auto)}, hỏi {len(asked)}.\n")
    print(f"{'game':>6} {'tướng':12s} nghe   kết quả")
    ok = wrong = ask = miss = 0
    used = set()  # mỗi dòng tiếng chỉ được tính cho một mốc HUD
    for gt, cid, cname in sorted(enemy_ev):
        near = [(i, g, m) for i, (g, m) in enumerate(heard) if abs(g - gt) <= args.tol and i not in used]
        if not near:
            miss += 1
            print(f"{int(gt)//60}:{int(gt)%60:02d} {cname:12s} -      SÓT (không nghe thấy)")
            continue
        verdict = "hỏi"
        pick = near[0][0]
        for i, g, m in near:  # ưu tiên dòng tự bấm đúng tướng này
            if "TỰ BẤM" in m and re.search(r"TỰ BẤM (\S+)", m).group(1) == cid:
                verdict, pick = "ĐÚNG", i
                break
        else:
            for i, g, m in near:
                if "TỰ BẤM" in m:
                    who = re.search(r"TỰ BẤM (\S+)", m).group(1)
                    verdict, pick = f"SAI (bấm {who})", i
                    break
        used.add(pick)
        ok += verdict == "ĐÚNG"
        wrong += verdict.startswith("SAI")
        ask += verdict == "hỏi"
        print(f"{int(gt)//60}:{int(gt)%60:02d} {cname:12s} có     {verdict}")
    print(f"\nFlash địch: {len(enemy_ev)} | nghe thấy {len(enemy_ev) - miss} | tự bấm đúng {ok} | bấm sai {wrong} | hỏi {ask} | không nghe {miss}")
    # tự bấm mà không có Flash HUD của tướng đó gần đó
    bad = 0
    for gt, cid in auto:
        if not any(abs(g - gt) <= args.tol and c == cid for g, c, _ in enemy_ev):
            bad += 1
            print(f"  tự bấm {cid} lúc {int(gt)//60}:{int(gt)%60:02d} nhưng HUD không có Flash của tướng đó")
    print(f"Tự bấm không có căn cứ: {bad}")


if __name__ == "__main__":
    main()
