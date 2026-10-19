# LOL Spell Timer: công nghệ và kỹ thuật bên trong

Tài liệu cho dev muốn hiểu tool này hoạt động thế nào, hoặc muốn tự làm một tool tương tự.
Toàn bộ logic nằm trong một file: [`spell_timer.py`](spell_timer.py), khoảng 800 dòng.

---

## 1. Tổng quan kiến trúc

```
                    ┌──────────────────────────── LOL Spell Timer ──────────────────────────────┐
 Riot Data Dragon   │  Assets (thread nền)            App (luồng UI - Tkinter)                  │
 (CDN công khai) ───┼─► tải champion.json,      ──►  EnemyRow ×5 ─ SpellSlot ×2 + UltSlot      │
                    │   summoner.json, ảnh PNG        ChampionPicker (Canvas, tạo 1 lần)         │
                    │   → cache/                      tick() mỗi 200ms: vẽ lại đồng hồ          │
 League client      │  Poller (thread nền)                ▲                                     │
 127.0.0.1:2999 ────┼─► GET /allgamedata mỗi 2s ── Lock ──┘ (UI tự đọc kết quả, không gọi chéo)  │
                    └───────────────────────────────────────────────────────────────────────────┘
                                         │
                       Windows DWM ghép cửa sổ "topmost" lên trên game (Borderless)
```

- **Không có input nào đi vào game.** App chỉ *đọc* dữ liệu Riot công khai và *hiện* một cửa sổ Windows riêng.
- Đồng hồ chỉ chạy khi người dùng tự click.

---

## 2. Ngôn ngữ và thư viện

**Ngôn ngữ:** Python 3.12. **Khi chạy app chỉ dùng thư viện chuẩn**, không cần `pip install` gì.

| Module | Dùng để làm gì |
|---|---|
| `tkinter` (Tk 8.6) | Toàn bộ giao diện: cửa sổ, Canvas, Menu, Entry, PhotoImage |
| `urllib.request` + `ssl` | Gọi Live Client API (HTTPS, chứng chỉ tự ký) và Data Dragon |
| `json` | Parse dữ liệu API, đọc/ghi `config.json` |
| `threading` | Hai luồng nền: Poller (API game), Assets (tải dữ liệu) |
| `concurrent.futures.ThreadPoolExecutor` | Tải song song 173 ảnh tướng (8 luồng) |
| `ctypes` | Gọi thẳng Win32 API `SetProcessDpiAwareness` để chữ nét trên màn hình scale 125–150% |
| `math` | Tính góc `atan2` cho hiệu ứng quét, `sin/cos` cho kim đồng hồ |
| `time.monotonic` | Đo thời gian đếm ngược (không bị ảnh hưởng khi đổi giờ hệ thống) |

**Chỉ dùng lúc build (không có trong exe):**

| Công cụ | Vai trò |
|---|---|
| [PyInstaller](https://pyinstaller.org) 6.x | Đóng gói Python và code thành một file `LOL Spell Timer.exe` |
| [Pillow](https://python-pillow.org) | Vẽ icon bằng code ([`tools/make_icon.py`](tools/make_icon.py)) |

---

## 3. Làm sao cửa sổ hiện đè lên game

Ba dòng quan trọng nhất trong `App.__init__`:

```python
self.root.overrideredirect(True)          # bỏ thanh tiêu đề + viền của Windows
self.root.attributes("-topmost", True)    # luôn nằm trên mọi cửa sổ thường
self.root.attributes("-alpha", 0.9)       # trong suốt 10%
```

Dưới đó, Tk gọi các Win32 API sau:

| Tkinter | Win32 tương ứng | Hiệu quả |
|---|---|---|
| `overrideredirect(True)` | style `WS_POPUP`, không có `WS_CAPTION` | Cửa sổ trơn, không viền. Vì vậy phải tự viết phần kéo thả (`drag_start` / `drag_move`) |
| `-topmost` | `SetWindowPos(hwnd, HWND_TOPMOST, …)` | Cửa sổ nằm trong nhóm "topmost", được vẽ trên các cửa sổ thường |
| `-alpha` | `WS_EX_LAYERED` + `SetLayeredWindowAttributes` | DWM trộn màu cửa sổ với nội dung phía sau |

**Click vào app mà không làm game mất focus: `WS_EX_NOACTIVATE`**

Mặc định, click vào một cửa sổ sẽ khiến Windows *kích hoạt* nó: cửa sổ đó thành foreground và nhận bàn phím. Game mất focus, bấm Q/W/E/R không còn tác dụng. App bật cờ extended style `WS_EX_NOACTIVATE` (bàn phím ảo On-Screen Keyboard cũng dùng cờ này). Với cờ này, click vẫn được gửi tới widget, nhưng Windows **không chuyển focus**:

```python
hwnd = int(root.wm_frame(), 16)                 # HWND khung ngoài của cửa sổ Tk
style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
```

Ba cái bẫy gặp phải khi làm:
- **Tk tự xóa cờ.** Tk giữ bản sao extended style riêng và ghi đè nó mỗi khi gọi `attributes("-alpha"/"-topmost")`. Đã đo thực tế: cờ mất ngay sau lần đổi độ trong suốt đầu tiên. Vì vậy `apply_opacity()` phải bật lại cờ.
- **Menu chuột phải.** Theo tài liệu `TrackPopupMenu`, cửa sổ sở hữu menu phải là foreground thì menu mới đóng khi click ra ngoài. `App.popup()` ghi nhớ cửa sổ đang có focus (game), tạm `SetForegroundWindow` cho app, mở menu, rồi trả focus cho game. Cách này dựa vào việc `tk_popup` trên Windows **chặn chờ** đến khi menu đóng mới trả về (đã đo: trả về đúng lúc menu đóng).
- **Ô tìm tướng cần bàn phím**, nên bảng chọn tướng vẫn lấy focus. Khi đóng bảng, focus được trả cho game, *trừ khi* người dùng đã click sang một app khác (không giành focus của app đó).

Cách test mà không cần mở LMHT: chạy một cửa sổ "game giả" ghi lại mọi phím nhận được, dùng `SetCursorPos` + `mouse_event` để click thật vào ô phép, rồi kiểm tra `GetForegroundWindow()` vẫn là game giả và phím gõ sau đó vẫn vào game giả.

**Icon ở khay hệ thống: Win32 thuần qua `ctypes`**

Tk không hỗ trợ khay hệ thống. Thư viện phổ biến là `pystray`, nhưng app tự làm bằng Win32 để giữ nguyên tắc "chỉ thư viện chuẩn" (class `TrayIcon`):

1. Tạo một **cửa sổ ẩn** (`RegisterClassW` + `CreateWindowExW`, không bao giờ hiện) chỉ để nhận message.
2. `Shell_NotifyIconW(NIM_ADD, …)` gắn icon vào khay, với `uCallbackMessage = WM_APP + 1`. Windows gửi message này vào cửa sổ ẩn mỗi khi người dùng thao tác chuột trên icon (`lParam` = `WM_LBUTTONUP` / `WM_RBUTTONUP`).
3. Vòng lặp `GetMessageW` / `DispatchMessageW` chạy ở **luồng riêng**. Hàm `wndproc` (một Python function bọc bằng `WINFUNCTYPE`, phải giữ tham chiếu kẻo bị thu gom) không chạm vào Tk mà chỉ đẩy sự kiện vào `queue.Queue`. `tick()` của Tk tự lấy ra xử lý.
4. Menu chuột phải: `CreatePopupMenu` + `TrackPopupMenu(TPM_RETURNCMD)`. Phải `SetForegroundWindow(cửa sổ ẩn)` trước và gửi `WM_NULL` sau, nếu không menu sẽ không tự đóng khi click ra ngoài (lỗi kinh điển ghi trong tài liệu của Microsoft).
5. Đăng ký message `"TaskbarCreated"`: khi Explorer khởi động lại, icon cũ biến mất và phải `NIM_ADD` lại.

Các lỗi gặp khi test:
- `wndproc` nhận message **ngay trong lúc** `CreateWindowExW` (`WM_NCCREATE`…), trước khi kịp gán thuộc tính. Thuộc tính nào `wndproc` dùng thì phải khởi tạo từ trước.
- Cửa sổ Tk được vẽ ra (và kích hoạt) ngay khi tạo, nên **giành focus của game lúc khởi động**. Cách sửa: `root.withdraw()` ngay sau `tk.Tk()`, chỉ hiện khi cần.
- Chọn "Thoát" từ khay: `quit()` chạy bên trong `tick()`, phần còn lại của `tick()` chạm vào widget đã hủy. `tick()` phải dừng ngay.

**Tự hiện / tự ẩn theo trận:** Live Client API chỉ mở khi đang trong trận. Có dữ liệu thì app hiện (`deiconify`, bật lại `WS_EX_NOACTIVATE`, trả focus cho cửa sổ trước đó). Mất dữ liệu **3 lần liên tiếp** (~6 giây) mới tính là hết trận, để một lần API chậm không làm cửa sổ nhấp nháy. Khi chạy từ exe, icon được nạp từ `sys._MEIPASS` (thư mục giải nén tạm của PyInstaller, thêm vào bằng `--add-data`).

**Vì sao phải để game ở chế độ Borderless (Không viền)?**

- **Borderless:** game chỉ là một cửa sổ phủ kín màn hình. **DWM** (Desktop Window Manager) vẫn ghép hình tất cả cửa sổ trước khi xuất ra màn hình, nên một cửa sổ topmost nằm đè lên được.
- **Fullscreen độc quyền (exclusive):** game chiếm thẳng đường xuất hình (swap chain đẩy thẳng ra màn hình, DWM không tham gia ghép hình). Không cửa sổ nào chen vào được, trừ khi *vẽ vào bên trong game* bằng cách hook DirectX. Đây đúng là việc mà anti-cheat theo dõi (xem mục 11).

Overlay của Porofessor (trên nền Overwolf) và Blitz vẽ *bên trong* game nhờ cơ chế được Riot chấp thuận. Tool này chọn cách an toàn hơn và đơn giản hơn: một cửa sổ riêng biệt.

---

## 4. Lấy dữ liệu trận: Live Client Data API

Khi bạn đang trong trận, client LMHT tự mở một web server cục bộ:

```
GET https://127.0.0.1:2999/liveclientdata/allgamedata
```

Kết quả là JSON gồm `activePlayer` (chính bạn), `allPlayers` (10 người: tướng, phép, đồ, vị trí, phe), `gameData.gameTime`…
Riot làm API này **dành riêng cho ứng dụng bên thứ ba**. Tài liệu: [developer.riotgames.com/docs/lol#game-client-api](https://developer.riotgames.com/docs/lol#game-client-api).

Những điểm đáng chú ý trong `Poller` và `apply_game_data`:

- **Chứng chỉ tự ký.** API dùng HTTPS với chứng chỉ do Riot tự ký, nên phải tắt kiểm tra chứng chỉ:
  ```python
  ctx = ssl.create_default_context()
  ctx.check_hostname = False
  ctx.verify_mode = ssl.CERT_NONE   # CHỈ chấp nhận được vì đích là 127.0.0.1
  ```
- **`ProxyHandler({})`.** Ép `urllib` bỏ qua proxy hệ thống. Nếu không, máy có cấu hình proxy (VPN công ty…) sẽ gửi cả request localhost qua proxy và lỗi.
- **Không phụ thuộc ngôn ngữ client.** `championName` / `displayName` đổi theo ngôn ngữ, nên app dùng các trường "raw":
  `rawChampionName = "game_character_displayname_MonkeyKing"` → id `MonkeyKing`,
  `rawDisplayName = "GeneratedTip_SummonerSpell_SummonerDot_DisplayName"` → Ignite.
- **Tìm phe địch bằng phép toán tập hợp:**
  ```python
  my_ids = {me.get("riotId"), me.get("summonerName")} - {None, ""}
  my_team = next((p["team"] for p in players if {p.get("riotId"), p.get("summonerName")} & my_ids), "ORDER")
  ```
- **Nhận ra trận mới** bằng một tuple "chữ ký" `((riotId, champion), …)`. Chữ ký đổi thì mới điền lại tướng/phép, nên các chỉnh sửa tay giữa trận không bị ghi đè mỗi 2 giây.
- **Tính điểm hồi từ trang bị** trong `items` của địch (thông tin vốn có trên bảng Tab), xem mục Kỹ năng Q/W/E/R.
- **Giờ game ước lượng:** `gameTime` (lần đọc gần nhất) + `monotonic() - lúc đọc`. Nhờ vậy nút Copy ra được `Zed Flash 14:40` mà không cần hỏi API liên tục.
- **Công thức điểm hồi phép bổ trợ:** `cd_thực = cd_gốc × 100 / (100 + haste)`.

---

## 5. Data Dragon và cache

[Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon) là CDN tĩnh của Riot, chứa dữ liệu và ảnh theo từng patch:

```
/api/versions.json                            → ["16.20.1", ...]
/cdn/{ver}/data/en_US/champion.json           → 173 tướng
/cdn/{ver}/data/en_US/summoner.json           → phép + cooldown
/cdn/{ver}/data/en_US/championFull.json       → toàn bộ chiêu của mọi tướng (lấy Q/W/E/R)
/cdn/{ver}/img/champion/{Id}.png              → avatar 128×128
/cdn/{ver}/img/spell/{SummonerFlash}.png      → icon 64×64
```

Kỹ thuật trong class `Assets`:

- **Cache theo version.** Lưu `version.txt`, chỉ tải lại JSON khi có patch mới. Ảnh nào đã có thì không tải lại.
- **Ghi file nguyên tử** để không bao giờ để lại file PNG hỏng nếu app tắt giữa chừng:
  ```python
  with open(path + ".tmp", "wb") as f: f.write(content)
  os.replace(path + ".tmp", path)      # đổi tên là thao tác nguyên tử trên cùng ổ đĩa
  ```
- **Tải song song:** `ThreadPoolExecutor(8).map(download, jobs)`. Lần đầu tải 184 file mất vài giây thay vì cả phút.
- **Chỉ giữ phần cần dùng.** `championFull.json` nặng 2,2MB (nén gzip còn ~430KB, nên request có gửi `Accept-Encoding: gzip` rồi tự `gzip.decompress`). App chỉ lấy tên, mảng cooldown và tên icon của Q/W/E/R, lưu thành `abilities.json` ~100KB.
- **Cooldown lấy từ Riot, cho phép ghi đè bằng tay.** Data Dragon ghi Smite 15s (thời gian nạp mỗi lượt tích trữ, không phải thời gian hồi thật), nên `config.json` có `cd_override: {"smite": 90}`.

---

## 6. Đa luồng với Tkinter: quy tắc "chỉ luồng UI được chạm vào widget"

Tk **không thread-safe**. Gọi `label.config(...)` từ thread khác có thể làm crash ngẫu nhiên. Mẫu mà app dùng:

```python
# Thread nền: chỉ ghi dữ liệu thuần, bảo vệ bằng Lock
with self.lock:
    self.latest = (data, time.monotonic())
    self.seq += 1

# Luồng UI: tự hỏi định kỳ bằng after() - giống setInterval trong JS
def tick(self):
    with self.poller.lock:
        seq, latest = self.poller.seq, self.poller.latest
    if seq != self.last_seq: ...            # chỉ xử lý khi có dữ liệu mới
    self.root.after(200, self.tick)
```

`Assets.changed` cũng làm theo cách đó: thread tải ảnh tăng bộ đếm, luồng UI thấy số đổi thì nạp ảnh mới vào widget.

---

## 7. Hiệu ứng "kim đồng hồ" khi phép đang hồi

Tk Canvas **không có alpha compositing và không cắt (clip) được ảnh theo hình quạt**, nên không thể "phủ một lớp đen 70% hình bánh". Cách làm là **tự tô từng điểm ảnh**:

1. **Đọc pixel PNG chỉ bằng một lệnh Tcl.** Tk 8.6 có lệnh `$photo data` trả về toàn bộ ảnh dạng `{#rrggbb #rrggbb …} {…}`:
   ```python
   rows = [[int(c[1:], 16) for c in src.tk.splitlist(row)]
           for row in src.tk.splitlist(src.tk.call(src.name, "data"))]
   ```
   Gọi `photo.get(x, y)` cho từng điểm sẽ tốn 4096 lần qua lại Python↔Tcl. Một lệnh `data` chỉ mất khoảng 5ms.
2. **Thu nhỏ 64→42px bằng box filter** (lấy trung bình từng vùng pixel). `PhotoImage.subsample` chỉ chia được theo số nguyên.
3. **Tính trước** hai bản màu (sáng / tối ×0.3) và **góc của từng điểm ảnh** tính từ 12 giờ theo chiều kim đồng hồ:
   ```python
   SWEEP_ANGLES = [math.degrees(math.atan2(x + .5 - S/2, S/2 - y - .5)) % 360
                   for y in range(S) for x in range(S)]
   ```
   `atan2(dx, -dy)` (đổi chỗ tham số so với thông thường) cho góc 0° ở 12 giờ, tăng theo chiều kim đồng hồ, đúng như đồng hồ trong game.
4. **Mỗi frame** chọn màu cho từng điểm rồi đẩy cả ảnh vào Tk bằng **một** lệnh `put`:
   ```python
   colors = [b if a < sweep else d for a, b, d in zip(SWEEP_ANGLES, bright, dark)]
   self.photo.put(" ".join("{" + " ".join(colors[y*S:(y+1)*S]) + "}" for y in range(S)))
   ```
5. **Chỉ vẽ lại khi có thay đổi.** `render()` so sánh tuple `(key, có_ảnh, góc_nguyên, chữ)` với lần trước. Phép hồi 300s chỉ đổi 1° sau mỗi 0,83s, nên phần lớn các tick không phải vẽ gì.
6. **Kim** là một `create_line` từ tâm, đầu kia ở `(mid + R·sin θ, mid − R·cos θ)`. **Chữ có bóng** là hai `create_text` lệch nhau 1px (đen bên dưới, trắng bên trên).

### Kỹ năng Q/W/E/R và kế thừa class

Ô phép bổ trợ và ô R dùng chung một lớp cơ sở `TimerSlot` (canvas, hiệu ứng quét, đếm ngược, click để bật/hủy). Lớp con chỉ cài 4 "hook":

```python
class TimerSlot:
    def cooldown(self): ...      # số giây hồi thực tế
    def load_pixels(self): ...   # icon nào
    def badge(self): ...         # chữ nhỏ ở góc (R1/R2/R3)
    def show_menu(self, e): ...  # menu chuột phải

class SpellSlot(TimerSlot): ...  # Flash/Ignite..., hồi theo "điểm hồi phép bổ trợ"
class AbilitySlot(TimerSlot): ... # Q/W/E/R của tướng đang chọn, hồi theo cấp kỹ năng + "điểm hồi kỹ năng"
```

Đây là mẫu *Template Method*: luồng xử lý chung nằm ở lớp cha, phần khác nhau đẩy xuống lớp con.

- **Cấp R theo level địch:** đa số tướng có 3 cấp R mở ở level 6/11/16. Elise, Nidalee và Karma có 4 cấp, mở từ level 1. App suy ra mốc level từ *độ dài mảng cooldown* (`ULT_RANK_LEVELS = {3: (6, 11, 16), 4: (1, 6, 11, 16)}`), nên không phải viết danh sách tên tướng ngoại lệ.
- **Tự động nhưng không giành quyền với người dùng:** chỉ đổi cấp R khi level địch *vừa vượt mốc mới* (`auto_rank` khác lần trước). Nếu người dùng chọn tay giữa hai mốc, giá trị đó được giữ lại.
- **Thêm / bỏ ô động:** ô mới được tạo, ô bị bỏ thì `frame.destroy()`. Sau mỗi lần thay đổi, `layout()` gỡ hết các ô bằng `pack_forget()` rồi xếp lại theo thứ tự cố định (phép, Q, W, E, R, nút +). Ô vẫn giữ trạng thái đếm ngược, vì chỉ đổi vị trí chứ không tạo lại.
- **Nhớ theo tướng:** danh sách kỹ năng lưu vào `config.json` → `champion_abilities` ngay khi thêm/bỏ.
- **Icon Q/W/E tải khi cần:** `Assets.ensure_icon()` mở thread tải đúng icon đó lần đầu được thêm, thay vì tải sẵn ~520 icon không dùng.
- **Phép đổi giữa trận (TP → TP+):** so sánh phép API báo lần này với lần trước. Chỉ đổi ô *đang hiện đúng phép cũ*, nên phép người dùng đã đổi tay không bị ghi đè, và đếm ngược được giữ (`keep_timer=True`).
- **Điểm hồi tự tính từ trang bị địch.** `item.json` của Data Dragon **không có trường số** cho điểm hồi, chỉ ghi trong mô tả HTML. `parse_item_haste()` đọc bằng 4 regex: chỉ số `<attention>20</attention> Ability Haste` (đọc trên HTML gốc để không nhầm với nội tại), và trên văn bản đã bỏ thẻ: "Gain 20 **Ultimate** Ability Haste", "Gain 25 **Basic** Ability Haste", "Gain 10 **Summoner Spell** Haste". Kết quả lưu thành `item_haste.json` (~230 món). Món có điểm hồi phụ thuộc chỉ số khác (Endless Hunger) thì không tính được.
- **Tổng điểm hồi = tự động + cộng tay.** `ability_haste_for(letter)` = trang bị + (hồi chiêu cuối nếu là R, hồi kỹ năng thường nếu là Q/W/E) + phần người dùng chọn. Phần cộng tay dành cho thứ API không lộ ra: ngọc phụ và mảnh chỉ số. Live API chỉ trả `keystone`, `primaryRuneTree`, `secondaryRuneTree` của địch, nên app chỉ *gợi ý* (vd có nhánh Cảm Hứng thì có thể có Thấu Thị Vũ Trụ).
- **Cùng một công thức cho cả hai loại hồi:** `cd × 100 / (100 + haste)`, chỉ khác nguồn haste.

---

## 8. Tối ưu bảng chọn tướng: từ ~1000ms xuống ~50ms

| Phiên bản | Cách làm | Thời gian mở |
|---|---|---|
| Cũ | Mỗi lần mở tạo `Toplevel` + 173 × (Frame + Label ảnh + Label tên) ≈ 520 widget, giải mã lại PNG | 430–1000 ms |
| Mới | Tạo **một lần**, mỗi tướng chỉ là 2 *item* trên **một Canvas**, mở/đóng bằng `deiconify()` / `withdraw()` | **~50 ms** |

Những bài học trong đó:

- **Widget đắt, canvas item rẻ.** Mỗi widget Tk là một cửa sổ con của Windows, kèm bố cục (geometry manager). Canvas item chỉ là dữ liệu vẽ. Ý tưởng này giống DOM nặng so với `<canvas>` trên web.
- **Lọc bằng cách di chuyển, không tạo lại:** `canvas.coords(item, x, y)` và `itemconfig(state="hidden")`.
- **Xác định ô được click bằng phép chia**, thay vì gắn 173 handler sự kiện:
  ```python
  col, line = int(x // CELL_W), int(y // CELL_H)
  i = line * COLS + col
  ```
- **Nạp ảnh dần lúc rảnh** (`preload_images`): mỗi lần nạp 6 ảnh rồi `after(15, …)` nhường luồng UI. Cách này giống `requestIdleCallback` trên web: app không bị khựng lúc khởi động, và đến lúc người dùng click thì ảnh đã sẵn sàng.
- **Ưu tiên kết quả bắt đầu bằng chữ đang gõ.** Hàm sort trả về `bool`, mà `False < True`:
  ```python
  found.sort(key=lambda c: not any(w.startswith(query) for w in keys[c].split()))
  ```
  `sort` của Python là *stable*, nên trong mỗi nhóm thứ tự A→Z được giữ nguyên.

**Đóng khi click ra ngoài:** bắt sự kiện `<FocusOut>` của bảng, nhưng **kiểm tra lại sau 50ms**:
```python
top.bind("<FocusOut>", lambda e: top.after(50, self.hide_if_unfocused))
```
`FocusOut` cũng bắn ra khi focus chỉ chuyển giữa các widget *bên trong* bảng. Phải đợi focus ổn định rồi hỏi `focus_get()`: nếu focus đã thuộc cửa sổ khác, hoặc là `None` (người dùng click sang game hay app khác) thì mới ẩn bảng.

---

## 9. Những chi tiết Python đáng học trong code

| Đoạn code | Vì sao thú vị |
|---|---|
| `lambda k=key: self.set_key(k)` | **Late binding.** Nếu viết `lambda: self.set_key(key)` trong vòng lặp, mọi menu item sẽ dùng `key` cuối cùng. Tham số mặc định "chụp" giá trị tại thời điểm tạo lambda |
| `r, g, b = (sum((p >> s) & 255 for p in area) // len(area) for s in (16, 8, 0))` | Tách kênh màu từ số 24-bit bằng dịch bit, rồi unpack thẳng một generator |
| `f"#{r:02x}{g:02x}{b:02x}"`, `f"{s // 60}:{s % 60:02d}"` | Format spec trong f-string: hex 2 chữ số, số có số 0 đứng đầu |
| `extra = {"image": icon, "compound": "left"} if icon else {}` rồi `add_command(..., **extra)` | Truyền tham số có điều kiện mà không phải lặp lại lời gọi hàm |
| `next((... for p in players if ...), "ORDER")` | Lấy phần tử đầu tiên thỏa điều kiện, có giá trị mặc định, dừng ngay khi tìm thấy |
| `{a, b} - {None, ""}` và `set_a & set_b` | Dùng phép toán tập hợp cho logic "có trùng id nào không" |
| `json.loads(json.dumps(DEFAULT_CONFIG))` | Deep copy nhanh cho dữ liệu kiểu JSON |
| `self.search.trace_add("write", ...)` | `StringVar` có thể "observe" được: tìm kiếm trực tiếp khi gõ mà không cần bắt phím |
| `APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))` | Với exe một file của PyInstaller, `__file__` trỏ vào thư mục tạm `_MEIxxxx` (bị xóa khi thoát). `sys.argv[0]` mới là đường dẫn thật của exe, nên `config.json` và `cache/` nằm cạnh exe |
| `ctypes.windll.shcore.SetProcessDpiAwareness(1)` | Gọi Win32 API trực tiếp, không cần pywin32 |

---

## 10. Đóng gói exe

[`build.bat`](build.bat) chạy hai bước:

1. `tools/make_icon.py`: vẽ icon bằng Pillow ở 1024px rồi thu về 256px (để có khử răng cưa), và xuất `.ico` nhiều cỡ 16→256. Icon gồm mặt đồng hồ bị phủ tối hình quạt, kim và tia chớp (Flash), tự vẽ hoàn toàn, không dùng tài sản của Riot.
2. PyInstaller:
   ```
   --onefile            gói tất cả vào một exe (~11MB, có kèm trình thông dịch Python)
   --windowed           không bật cửa sổ console đen
   --icon               icon của file exe
   --version-file       thông tin trong Properties → Details (tên sản phẩm, phiên bản)
   ```

Đánh đổi của `--onefile`: mỗi lần chạy, exe giải nén vào `%TEMP%\_MEIxxxx`, nên khởi động chậm hơn 1–2 giây và tốn khoảng 55MB RAM. Một số antivirus còn báo nhầm, vì loader của PyInstaller rất phổ biến trong cả mã độc. Cách khác là `--onedir` (khởi động nhanh hơn, nhưng là cả một thư mục) hoặc tự ký số (code signing) cho exe.

---

## 11. Anti-cheat: phần mềm nào bị coi là can thiệp game?

LMHT dùng **Riot Vanguard** (từ 2024). Đây là anti-cheat chạy ở **kernel** (driver `vgk.sys` khởi động cùng Windows), nên nhìn thấy được mọi thứ chạm vào tiến trình game. Có hai lớp kiểm soát: **kỹ thuật** (Vanguard phát hiện) và **chính sách** (Riot cấm, dù kỹ thuật có thể không vi phạm).

### 11.1. Lớp kỹ thuật: những hành vi Vanguard theo dõi

| Hành vi | Ví dụ phần mềm | Vì sao bị bắt |
|---|---|---|
| **Đọc bộ nhớ game** (`OpenProcess` + `ReadProcessMemory`) | Script đọc vị trí, máu, cooldown địch; "map hack" | Lấy thông tin game không hiển thị cho người chơi |
| **Ghi bộ nhớ game** (`WriteProcessMemory`) | Sửa tầm nhìn camera (zoom hack), mở khóa skin | Thay đổi trạng thái game |
| **Chèn DLL / chạy code trong tiến trình game** | Hầu hết hack, kể cả overlay tự làm | Code lạ chạy *bên trong* `League of Legends.exe` |
| **Hook DirectX / hàm của game** | Overlay tự vẽ lên game, ESP | Chặn và sửa luồng vẽ hoặc logic của game |
| **Driver kernel lạ hoặc có lỗ hổng** | Cheat tầm kernel, driver cũ có lỗi bảo mật bị lợi dụng | Vanguard chặn driver nằm trong danh sách đen |
| **Tự động hóa thao tác chơi** | Orbwalker, auto-dodge, script combo, macro | Máy chơi thay người. Dù chỉ giả lập phím chuột bằng `SendInput`, các mẫu thao tác bất thường vẫn bị phát hiện |
| **Sửa file game / gói tin mạng** | Mod file, chỉnh sửa gói tin | Phá tính toàn vẹn của client |

### 11.2. Lớp chính sách: dùng API chính thức vẫn có thể bị cấm

Riot có [chính sách cho ứng dụng bên thứ ba](https://developer.riotgames.com/policies/general). Tinh thần chung là ứng dụng **không được làm thay việc mà người chơi phải tự làm** và **không được đưa ra thông tin người chơi không tự có được**. Ví dụ bị cấm:

- **Tự động** theo dõi thời gian hồi phép bổ trợ hoặc chiêu cuối của địch.
- Tự động đếm giờ quái rừng hoặc rồng mà người chơi không nhìn thấy.
- Hiện thông tin bị che (ví dụ vị trí địch trong sương mù).
- Ra quyết định thay người chơi trong trận (kiểu "bây giờ hãy gank đường giữa").

Vì vậy một tool **chụp màn hình rồi tự nhận ra địch vừa dùng Flash** vẫn vi phạm, dù không chạm vào bộ nhớ game.

> Chính sách có thể thay đổi. Hãy đọc bản mới nhất trên developer.riotgames.com trước khi mở rộng tool.

### 11.3. Vì sao UniKey không bị ban?

UniKey về mặt kỹ thuật **khá "xâm nhập"**: nó cài **hook bàn phím toàn hệ thống** (`SetWindowsHookEx(WH_KEYBOARD_LL)`) để bắt mọi phím bạn gõ. Sau đó nó **gửi phím giả** (`SendInput`: vài phím Backspace rồi ký tự Unicode) để đổi `aa` thành `â`. Nhưng:

1. **Không chạm vào tiến trình game.** UniKey không đọc hay ghi bộ nhớ game, không chèn DLL. Mọi thứ đi qua hàng đợi input chuẩn của Windows, giống như bàn phím thật.
2. **Đầu ra phụ thuộc 1:1 vào việc người dùng gõ.** UniKey chỉ biến đổi văn bản bạn tự gõ, không tự sinh ra thao tác chơi. Nó không bấm combo, không né chiêu thay bạn.
3. **Không mang lại lợi thế.** Gõ tiếng Việt trong khung chat không giúp thắng trận.
4. **Phổ biến và có mục đích rõ ràng.** Bộ gõ (IME) là phần mềm hệ thống cơ bản. Anti-cheat chấm điểm theo *hành vi nhắm vào game* và *chữ ký của cheat đã biết*, chứ không cấm mọi chương trình có hook bàn phím. Nếu cấm thì cả Unikey, EVKey, bộ gõ tiếng Nhật/Trung, phần mềm hỗ trợ người khuyết tật… đều chết.

Nói cách khác, cùng một kỹ thuật (`SendInput`): dùng để **gõ chữ người dùng muốn** thì hợp lệ, dùng để **tự động chơi** thì là macro và vi phạm. Ranh giới nằm ở **mục đích và đối tượng tác động**, không nằm ở API.

### 11.4. Vì sao LOL Spell Timer không vi phạm?

| Tiêu chí | LOL Spell Timer |
|---|---|
| Đọc/ghi bộ nhớ game | ❌ Không. Không hề mở handle tới tiến trình game |
| Chèn code / hook DirectX | ❌ Không. Là một cửa sổ Windows riêng, do DWM ghép hình |
| Gửi input vào game | ❌ Không. Không hook bàn phím, không `SendInput`. Ngay cả nút Copy cũng chỉ ghi vào clipboard, bạn tự Ctrl+V |
| Focus | Chỉ đổi thuộc tính cửa sổ *của chính app* (`WS_EX_NOACTIVATE`) và trả focus bằng `SetForegroundWindow`, tương đương việc Alt+Tab. Không gửi phím hay chuột nào vào game |
| Nguồn dữ liệu | ✅ Live Client Data API chính thức, do Riot mở cho app bên thứ ba (cùng nguồn với Porofessor/Blitz) và Data Dragon (CDN công khai) |
| Thông tin hiển thị | ✅ Tướng, phép, giày của địch đều có trên bảng Tab |
| Theo dõi cooldown địch | ✅ **Bấm tay**: chỉ đếm khi người dùng tự thấy và tự click. Đây là trường hợp chính sách cho phép |
| Chiêu cuối (R) | ✅ Cũng bấm tay. App chỉ tự chọn *cấp* R từ level của địch (có trên bảng Tab), tức là tính sẵn "nếu dùng thì hồi bao lâu". App không bao giờ tự biết địch đã dùng R hay chưa |
| Driver / quyền admin | ❌ Không cần. Chạy với quyền user bình thường |

Với Vanguard, tool này nhìn không khác gì Notepad hay một trình duyệt mở `localhost`.

**Nhưng không có gì đảm bảo 100%.** Riot là bên quyết định cuối cùng và có thể đổi chính sách. Nếu sửa tool, **đừng** thêm những thứ sau, vì chúng biến tool thành vi phạm:

- Tự bắt đầu đếm ngược khi phát hiện địch dùng phép, dù bằng cách đọc bộ nhớ, đọc log hay nhận diện hình ảnh.
- Hook phím tắt toàn cục để bấm đếm ngay trong lúc game đang focus. Tool sẽ phải cài hook bàn phím, rơi vào vùng xám về kỹ thuật.
- Tự gửi tin nhắn vào chat game bằng giả lập phím.
- Vẽ overlay bên trong game bằng cách hook DirectX.

---

## 12. Gợi ý tìm hiểu thêm

- **Riot Developer Portal:** Game Client API, Data Dragon, chính sách bên thứ ba.
- **Tkinter Canvas và PhotoImage:** [tkdocs.com](https://tkdocs.com), và trang `photo` trong tài liệu Tcl/Tk (các lệnh `data`, `put`, `copy -subsample/-zoom`).
- **Win32:** `SetWindowPos`/`HWND_TOPMOST`, layered windows, DWM composition, sự khác nhau giữa exclusive fullscreen và borderless.
- **Python:** `concurrent.futures`, closure và late binding, `ctypes`.
- **PyInstaller:** chế độ onefile và onedir, file `.spec`, `sys._MEIPASS`.
