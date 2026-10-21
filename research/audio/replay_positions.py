"""Lấy vị trí của cả 10 tướng theo thời gian từ replay: lần lượt gắn camera vào từng người qua
Replay API và đọc cameraPosition. Không ghi âm thanh (camera nhảy liên tục nên tiếng vô nghĩa).

    python replay_positions.py 1609077581 --speed 2 --interval 0.2

Mỗi `interval` giây thực chuyển camera sang người tiếp theo, nên mỗi người có một mốc vị trí mỗi
10*interval*speed giây game. Kết quả sessions/positions_<gameId>_<time>/positions.csv:
    t, time, player, champion, team, x, z        (time = giây replay, x/z = tọa độ bản đồ)
Dùng để biết Flash (từ flash_events.csv của phiên âm thanh) cách camera bao xa.
"""
import argparse
import csv
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SESSIONS_DIR  # noqa: E402
from replay_session import COMPONENT, LCU, ensure_downloaded, game_api, wait_game_api  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_id", type=int)
    ap.add_argument("--out", default=SESSIONS_DIR)
    ap.add_argument("--speed", type=float, default=2.0)
    ap.add_argument("--interval", type=float, default=0.2)
    ap.add_argument("--kill", action="store_true")
    args = ap.parse_args()

    lcu = LCU()
    ensure_downloaded(lcu, args.game_id)
    st, _ = game_api("/replay/playback")
    if st != 200:
        print("Mở replay...", lcu("POST", f"/lol-replays/v1/rofls/{args.game_id}/watch", COMPONENT))
    pb = wait_game_api()
    if pb is None:
        raise SystemExit("Replay API không trả lời")
    game_api("/replay/playback", {"paused": True, "speed": args.speed, "time": 0})
    for _ in range(60):
        st, data = game_api("/liveclientdata/allgamedata")
        if st == 200 and len(data.get("allPlayers", [])) >= 10:
            break
        time.sleep(1)
    players = [(p.get("riotIdGameName") or p["summonerName"], p["championName"], p["team"]) for p in data["allPlayers"]]
    print("Người chơi:", ", ".join(f"{n} ({c})" for n, c, _ in players))

    session = os.path.join(args.out, f"positions_{args.game_id}_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(session, exist_ok=True)
    game_api("/replay/render", {"fogOfWar": False})
    # lúc game còn đang tải, lệnh bỏ tạm dừng bị bỏ qua: gửi lại cho tới khi time chạy
    for _ in range(60):
        game_api("/replay/playback", {"paused": False, "speed": args.speed})
        time.sleep(2)
        st, pb = game_api("/replay/playback")
        if st == 200 and not pb["paused"] and pb["time"] > 0.5:
            break
    t0 = time.perf_counter()
    n = fails = 0
    with open(os.path.join(session, "positions.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "time", "player", "champion", "team", "x", "z"])
        try:
            while True:
                name, champ, team = players[n % len(players)]
                st, r = game_api("/replay/render", {"selectionName": name, "cameraAttached": True})
                st2, pb = game_api("/replay/playback")
                t = time.perf_counter() - t0
                if st == 200 and st2 == 200 and r.get("selectionName") == name:
                    fails = 0
                    pos = r["cameraPosition"]
                    w.writerow([f"{t:.3f}", f"{pb['time']:.3f}", name, champ, team, f"{pos['x']:.0f}", f"{pos['z']:.0f}"])
                    if n % 50 == 0:
                        f.flush()
                        print(f"\r{t:7.0f}s  replay {pb['time']:7.1f}/{pb['length']:.0f}s  {n} mẫu   ", end="", flush=True)
                    if pb["time"] >= pb["length"] - 1.5:
                        print("\nHết replay")
                        break
                else:
                    fails += 1
                    if fails > 50:
                        print("\nMất kết nối Replay API")
                        break
                n += 1
                time.sleep(max(0, args.interval - (time.perf_counter() - t0 - t)))
        except KeyboardInterrupt:
            pass
    if args.kill:
        subprocess.run(["taskkill", "/IM", "League of Legends.exe", "/F"], capture_output=True)
    print("Xong:", session)


if __name__ == "__main__":
    main()
