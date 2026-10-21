"""Mở replay của một trận bằng LCU, gắn camera vào tướng của người chơi, phát ở tốc độ 1x và ghi
một phiên đo (âm thanh loopback + ảnh màn hình + giờ game) cho tới khi hết replay.

    python replay_session.py 1609077581              # tải (nếu chưa có), mở, ghi đủ
    python replay_session.py 1609077581 --no-screen  # chỉ âm thanh + giờ game
    python replay_session.py 1609077581 --list       # chỉ in lịch sử đấu rồi thoát

Kết quả: sessions/replay_<gameId>_<YYYYmmdd_HHMMSS>/ như record.py, thêm:
    replay.csv     t, time, paused, speed   (từ /replay/playback, mỗi 2 giây)
    replay.json    gameId, tướng của người chơi, danh sách 10 người (từ allgamedata)

Cần client LMHT đang mở và đã đăng nhập (đọc lockfile). Tắt nhạc game trước khi đo:
    PATCH /lol-game-settings/v1/game-settings {"Volume":{"MusicMute":true}} rồi POST /lol-game-settings/v1/save
Game tắt tiếng khi mất focus, nên đừng click sang cửa sổ khác trong lúc ghi.
"""
import argparse
import base64
import csv
import json
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SESSIONS_DIR  # noqa: E402
from record import Recorder  # noqa: E402

LOCKFILE = r"C:\Riot Games\League of Legends\lockfile"
GAME_API = "https://127.0.0.1:2999"
COMPONENT = {"componentType": "replay-button_match-history"}

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                      urllib.request.HTTPSHandler(context=_ctx))


def _request(url, method="GET", body=None, headers=None, timeout=10):
    req = urllib.request.Request(url, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          **(headers or {})})
    try:
        with _opener.open(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")
    except (urllib.error.URLError, OSError) as e:  # game chưa mở / đã đóng
        return 0, str(e)


class LCU:
    def __init__(self):
        parts = open(LOCKFILE).read().split(":")
        self.port, pw = parts[2], parts[3]
        self.auth = {"Authorization": "Basic " + base64.b64encode(f"riot:{pw}".encode()).decode()}

    def __call__(self, method, path, body=None):
        return _request(f"https://127.0.0.1:{self.port}{path}", method, body, self.auth)


def game_api(path, body=None):
    return _request(GAME_API + path, "GET" if body is None else "POST", body, timeout=3)


def list_matches(lcu, n=40):
    st, d = lcu("GET", f"/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex={n}")
    if st != 200:
        raise SystemExit(f"match history: {st} {d}")
    for g in d["games"]["games"]:
        me = g["participants"][0]
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(g["gameCreation"] / 1000))
        print(f"{g['gameId']}  {ts}  {g['gameMode']:9s} queue {g.get('queueId')}  "
              f"{g['gameDuration'] // 60}:{g['gameDuration'] % 60:02d}  {g['gameVersion']}  "
              f"champ {me['championId']}  {'win' if me['stats']['win'] else 'loss'}")


def ensure_downloaded(lcu, game_id):
    st, meta = lcu("GET", f"/lol-replays/v1/metadata/{game_id}")
    if st != 200 or meta.get("state") != "watch":
        print(f"Tải replay {game_id}...")
        lcu("POST", f"/lol-replays/v1/rofls/{game_id}/download", COMPONENT)
        for _ in range(120):
            time.sleep(2)
            st, meta = lcu("GET", f"/lol-replays/v1/metadata/{game_id}")
            if st == 200:
                print(f"\r  {meta.get('state')} {meta.get('downloadProgress')}%   ", end="", flush=True)
                if meta.get("state") == "watch":
                    break
                if meta.get("state") in ("lost", "incompatible", "error"):
                    raise SystemExit(f"\nreplay không dùng được: {meta}")
        print()
    if meta.get("state") != "watch":
        raise SystemExit(f"replay chưa sẵn sàng: {meta}")


def wait_game_api(timeout=180):
    """Chờ tiến trình game mở và Replay API trả lời. Trả về playback hoặc None."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, pb = game_api("/replay/playback")
        if st == 200 and isinstance(pb, dict) and pb.get("length", 0) > 0:
            return pb
        time.sleep(2)
    return None


def my_champion(data, game_name, tag):
    for p in data.get("allPlayers", []):
        rid = p.get("riotId") or p.get("summonerName") or ""
        if rid.lower() == f"{game_name}#{tag}".lower() or p.get("riotIdGameName", "").lower() == game_name.lower():
            return p
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_id", nargs="?", type=int)
    ap.add_argument("--list", action="store_true", help="in lịch sử đấu rồi thoát")
    ap.add_argument("--out", default=SESSIONS_DIR)
    ap.add_argument("--fps", type=float, default=4)
    ap.add_argument("--monitor", type=int, default=0)
    ap.add_argument("--no-screen", action="store_true")
    ap.add_argument("--hud-only", action="store_true", help="chỉ lưu hai cột HUD (ảnh nhẹ, đủ cho hud_flash.py)")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--fog", choices=["Xanh", "Đỏ", "Tất cả"], help="chọn phe nhìn thấy trên minimap (cần game ở foreground, 1080p)")
    ap.add_argument("--start", type=float, default=0, help="giây replay bắt đầu ghi")
    ap.add_argument("--kill", action="store_true", help="đóng game khi hết replay")
    args = ap.parse_args()

    lcu = LCU()
    if args.list or args.game_id is None:
        list_matches(lcu)
        return

    st, me = lcu("GET", "/lol-summoner/v1/current-summoner")
    game_name, tag = me.get("gameName", ""), me.get("tagLine", "")
    ensure_downloaded(lcu, args.game_id)

    st, pb = game_api("/replay/playback")
    if st != 200:
        print(f"Mở replay {args.game_id}...")
        st, d = lcu("POST", f"/lol-replays/v1/rofls/{args.game_id}/watch", COMPONENT)
        print("  watch:", st, d)
    pb = wait_game_api()
    if pb is None:
        raise SystemExit("Replay API không trả lời (game chưa mở?)")
    print("Playback:", pb)

    # tạm dừng để chuẩn bị camera, lấy đội hình
    game_api("/replay/playback", {"paused": True, "speed": args.speed, "time": args.start})
    st, data = game_api("/liveclientdata/allgamedata")
    for _ in range(60):  # lúc mới tải, allPlayers chỉ có 1-2 người
        if st == 200 and len(data.get("allPlayers", [])) >= 10:
            break
        time.sleep(1)
        st, data = game_api("/liveclientdata/allgamedata")
    mine = my_champion(data, game_name, tag) if st == 200 else None
    if mine is None and st == 200 and data.get("allPlayers"):
        # replay của người khác: gắn camera vào người đầu phe ORDER (app coi ORDER là phe mình khi không có activePlayer)
        mine = next((p for p in data["allPlayers"] if p.get("team") == "ORDER"), data["allPlayers"][0])
        print(f"Người chơi không có trong trận; gắn camera vào {mine.get('riotIdGameName')} ({mine['championName']}, {mine['team']})")
    st_r, render = game_api("/replay/render")
    print("Render hiện tại:", {k: render.get(k) for k in ("cameraAttached", "cameraMode", "selectionName", "selectionOffset")}
          if st_r == 200 else (st_r, render))
    if mine:
        print(f"Tướng của {game_name}#{tag}: {mine['championName']} ({mine['team']})")
        # selectionName nhận riotIdGameName (phần trước dấu #), không nhận tên tướng
        name = mine.get("riotIdGameName") or game_name
        st_r, render = game_api("/replay/render", {"selectionName": name, "cameraAttached": True})
        if st_r == 200 and render.get("selectionName") == name:
            print("  camera gắn vào", name)
        else:
            print("  không gắn được camera:", st_r, render)
    else:
        print("Không tìm thấy người chơi trong allPlayers; giữ camera mặc định")

    session = os.path.join(args.out, f"replay_{args.game_id}_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(session, exist_ok=True)
    with open(os.path.join(session, "replay.json"), "w", encoding="utf-8") as f:
        json.dump({"gameId": args.game_id, "me": f"{game_name}#{tag}",
                   "myChampion": mine and mine["championName"], "playback": pb, "render": render,
                   "players": [{k: p.get(k) for k in ("riotId", "championName", "team", "summonerSpells")}
                               for p in data.get("allPlayers", [])]}, f, ensure_ascii=False, indent=1)

    if args.fog:
        from replay_ui import set_fog
        set_fog(args.fog)
        print("Sương mù:", args.fog)
    rec = Recorder(session, args.fps, args.monitor, not args.no_screen, True, hud_only=args.hud_only)
    threads = [threading.Thread(target=rec.run_audio, daemon=True),
               threading.Thread(target=rec.run_game, daemon=True)]
    if not args.no_screen:
        threads.append(threading.Thread(target=rec.run_screen, daemon=True))
    rec.t0 = time.perf_counter()
    for t in threads:
        t.start()
    time.sleep(1)
    # lúc game còn đang tải, lệnh bỏ tạm dừng bị bỏ qua: gửi lại cho tới khi time chạy
    for _ in range(90):
        game_api("/replay/playback", {"paused": False, "speed": args.speed})
        time.sleep(2)
        st, pb = game_api("/replay/playback")
        if st == 200 and not pb["paused"] and pb["time"] > 0.5:
            break
    print(f"Đang ghi vào {session}. Tạo file STOP trong thư mục phiên để dừng sớm.")

    stop_file = os.path.join(session, "STOP")
    fails = 0
    with open(os.path.join(session, "replay.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "time", "paused", "speed"])
        try:
            while True:
                time.sleep(2)
                if os.path.exists(stop_file):
                    print("\nCó file STOP")
                    break
                st, pb = game_api("/replay/playback")
                t = time.perf_counter() - rec.t0
                if st == 200 and isinstance(pb, dict):
                    fails = 0
                    w.writerow([f"{t:.3f}", pb["time"], pb["paused"], pb["speed"]])
                    f.flush()
                    print(f"\r{t:7.0f}s  replay {pb['time']:7.1f}/{pb['length']:.0f}s  ảnh {rec.frames_saved}"
                          f"  giờ game {rec.game_rows}  gap {rec.gaps}   ", end="", flush=True)
                    if pb["time"] >= pb["length"] - 1.5:
                        print("\nHết replay")
                        break
                else:
                    fails += 1
                    if fails >= 8:
                        print("\nReplay API mất kết nối (game đã đóng?)")
                        break
        except KeyboardInterrupt:
            pass
    print("Đang dừng...")
    rec.stop.set()
    for t in threads:
        t.join(timeout=5)
    if args.kill:
        subprocess.run(["taskkill", "/IM", "League of Legends.exe", "/F"], capture_output=True)
    print("Xong:", session)


if __name__ == "__main__":
    main()
