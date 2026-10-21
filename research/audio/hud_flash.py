"""Mốc Flash của cả 10 người chơi từ HUD replay: hai cột khung tướng bên trái/phải màn hình hiện
phép bổ trợ của từng người, ô Flash sáng vàng khi sẵn sàng và tối (có số đếm ngược) khi hồi.

    python hud_flash.py sessions/replay_<x>            # xuất flash_events.csv + hud_yellow.npy
    python hud_flash.py sessions/replay_<x> --plot     # thêm hud_yellow.png để nhìn tín hiệu

Tọa độ cho ảnh 960x540, replay HUD mặc định: cột trái x 4:12, cột phải x 949:955, hàng đầu
y 79:88, mỗi hàng cách 51 px, ô phép 1 rồi phép 2 (cách 11 px) rồi R. Thứ tự hàng = thứ tự
allPlayers trong allgamedata.json (5 ORDER bên trái, 5 CHAOS bên phải).

flash_events.csv: t, gameTime, player, champion, team, slot, yellow_before, yellow_after
"""
import argparse
import csv
import json
import os

import cv2
import numpy as np

ROW0, PITCH = 79, 51
SLOT_DY = 11
LEFT_X, RIGHT_X = (5, 11), (949, 955)
ICON_H = 8  # y: ROW0+1 .. ROW0+1+ICON_H
SPELL = "flash"  # --spell: phép cần lấy mốc; ô sáng/tối đọc giống nhau cho mọi phép bổ trợ
SPELL_KEYS = {"flash": ("SummonerFlash", "Flash", "Tốc Biến"), "ignite": ("SummonerDot", "Thiêu Đốt", "Ignite"),
              "heal": ("SummonerHeal", "Hồi Máu"), "exhaust": ("SummonerExhaust", "Kiệt Sức"),
              "barrier": ("SummonerBarrier", "Lá Chắn"), "teleport": ("SummonerTeleport", "Dịch Chuyển")}
READY_HI, READY_LO = 50, 35  # độ vàng (R+G)/2-B: sẵn sàng ~68-78; đang hồi ~20-25 (lớp phủ bán trong suốt, dao động theo nền)
STABLE = 4  # khung (1 s ở 4 fps) ổn định trước và sau mốc


def yellow(region):
    b, g, r = region[..., 0].astype(float), region[..., 1].astype(float), region[..., 2].astype(float)
    return float(((r + g) / 2 - b).mean())


CROP = None  # hud_crop.json của phiên ghi --hud-only: ảnh = [cột trái | cột phải] đã cắt


def slot_box(side, row, slot):
    x0, x1 = LEFT_X if side == "left" else RIGHT_X
    y0 = ROW0 + 1 + row * PITCH + slot * SLOT_DY
    if CROP:
        y0 -= CROP["y0"]
        dx = -CROP["left_x0"] if side == "left" else CROP["width"] - CROP["right_x0"]
        x0, x1 = x0 + dx, x1 + dx
    return slice(y0, y0 + ICON_H), slice(x0, x1)


def load_players(session):
    with open(os.path.join(session, "allgamedata.json"), encoding="utf-8") as f:
        data = json.load(f)
    players = []
    for p in data["allPlayers"]:
        ss = p["summonerSpells"]
        flash_slot = None
        for i, key in enumerate(("summonerSpellOne", "summonerSpellTwo")):
            name = ss[key]["rawDisplayName"] + " " + ss[key]["displayName"]
            if any(k in name for k in SPELL_KEYS[SPELL]):
                flash_slot = i
        players.append({"name": p.get("riotIdGameName") or p.get("summonerName"),
                        "champion": p["championName"], "team": p["team"], "flash_slot": flash_slot})
    order = [p for p in players if p["team"] == "ORDER"]
    chaos = [p for p in players if p["team"] == "CHAOS"]
    for i, p in enumerate(order):
        p["side"], p["row"] = "left", i
    for i, p in enumerate(chaos):
        p["side"], p["row"] = "right", i
    return players


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--spell", default="flash", choices=sorted(SPELL_KEYS))
    args = ap.parse_args()
    session = args.session
    global SPELL
    SPELL = args.spell

    global CROP
    if os.path.exists(os.path.join(session, "hud_crop.json")):
        with open(os.path.join(session, "hud_crop.json")) as f:
            CROP = json.load(f)
    players = load_players(session)
    with open(os.path.join(session, "frames.csv"), newline="") as f:
        frames = list(csv.DictReader(f))
    game = []
    if os.path.exists(os.path.join(session, "game.csv")):
        with open(os.path.join(session, "game.csv"), newline="") as f:
            game = list(csv.DictReader(f))
    gt_t = np.array([float(r["t"]) for r in game])
    gt_g = np.array([float(r["gameTime"]) for r in game])

    cache = os.path.join(session, "hud_yellow.npy")
    if os.path.exists(cache) and np.load(cache).shape[0] == len(frames):
        Y = np.load(cache)
    else:
        Y = np.full((len(frames), len(players), 2), np.nan)  # độ vàng ô phép 1, phép 2
        for i, r in enumerate(frames):
            img = cv2.imread(os.path.join(session, "frames", r["file"]))
            if img is None:
                continue
            for j, p in enumerate(players):
                for slot in range(2):
                    Y[i, j, slot] = yellow(img[slot_box(p["side"], p["row"], slot)])
            if i % 500 == 0:
                print(f"\r{i}/{len(frames)} khung", end="", flush=True)
        print()
        np.save(cache, Y)
    t = np.array([float(r["t"]) for r in frames])

    print(f"{len(frames)} khung, {len(players)} người chơi")
    print(f"{'người chơi':22s} {'tướng':12s} {'ô Flash':7s} {'vàng 5%':>8s} {'50%':>6s} {'95%':>6s}")
    for j, p in enumerate(players):
        s = p["flash_slot"]
        if s is None:
            print(f"{p['name']:22s} {p['champion']:12s} không mang Flash")
            continue
        q = np.nanpercentile(Y[:, j, s], [5, 50, 95])
        print(f"{p['name']:22s} {p['champion']:12s} {s + 1:7d} {q[0]:8.1f} {q[1]:6.1f} {q[2]:6.1f}")

    events = []
    for j, p in enumerate(players):
        s = p["flash_slot"]
        if s is None:
            continue
        hi, lo = Y[:, j, s] > READY_HI, Y[:, j, s] < READY_LO
        state = None  # ngưỡng kép: "ready" khi sáng ổn định, "cd" khi tối ổn định
        for i in range(STABLE, len(t) - STABLE):
            if state != "ready" and hi[i - STABLE:i].all():
                state = "ready"
            elif state == "ready" and lo[i:i + STABLE].all():
                state = "cd"
                events.append({"t": t[i], "player": p["name"], "champion": p["champion"], "team": p["team"],
                               "slot": s + 1, "yellow_before": float(Y[i - 1, j, s]), "yellow_after": float(Y[i, j, s])})
    events.sort(key=lambda e: e["t"])
    # cuối trận / màn hình tải: cả HUD tối cùng lúc -> >= 3 người "Flash" trong 1 s là giả
    ts = np.array([e["t"] for e in events])
    events = [e for e in events if (np.abs(ts - e["t"]) <= 1.0).sum() < 3]

    out = os.path.join(session, f"{SPELL}_events.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["t", "gameTime", "player", "champion", "team", "slot", "yellow_before", "yellow_after"])
        w.writeheader()
        for e in events:
            gt = float(np.interp(e["t"], gt_t, gt_g)) if len(game) else float("nan")
            e["gameTime"] = f"{gt:.1f}"
            e["t"] = f"{e['t']:.2f}"
            e["yellow_before"] = f"{e['yellow_before']:.1f}"
            e["yellow_after"] = f"{e['yellow_after']:.1f}"
            w.writerow(e)
    print(f"\n{len(events)} lần Flash (sáng -> tối):")
    for e in events:
        gt = float(e["gameTime"])
        print(f"  t={float(e['t']):8.2f}s  game {int(gt) // 60}:{int(gt) % 60:02d}  {e['team']:5s} {e['champion']:12s} {e['player']}")
    print("Đã ghi", out)

    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(len(players), 1, figsize=(16, 1.2 * len(players)), sharex=True, squeeze=False)
        axes = axes[:, 0]
        for j, p in enumerate(players):
            s = p["flash_slot"]
            if s is None:
                continue
            axes[j].plot(t, Y[:, j, s], lw=0.6)
            axes[j].axhline(READY_HI, color="g", lw=0.5)
            axes[j].axhline(READY_LO, color="r", lw=0.5)
            axes[j].set_ylabel(p["champion"], rotation=0, ha="right", fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(session, "hud_yellow.png"), dpi=100)
        print("Đã vẽ", os.path.join(session, "hud_yellow.png"))


if __name__ == "__main__":
    main()
