# Nghiên cứu: nhận ra tiếng Tốc Biến (Flash) từ âm thanh game

Ghi lại toàn bộ những gì đã làm, đo được và còn bỏ ngỏ trong đợt thử nghiệm ngày 19/10/2026,
để có thể tiếp tục trên máy khác. Code nằm trong thư mục này, tách hẳn khỏi app chính
([`spell_timer.py`](../../spell_timer.py) không bị sửa).

**Kết luận ngắn:** trong Practice Tool, so mẫu âm thanh nhận ra Flash gần như hoàn hảo
(9/9, điểm 0,85–0,93, nền ≤ 0,42). Trong một trận thật 27 phút, cùng phương pháp **không tách
được Flash khỏi nhiễu**: 6 lần Flash địch được gắn nhãn tay chỉ đạt 0,25–0,61, trong khi nhiễu
nền lên tới 0,69. Nguyên nhân chính đo được là tiếng Flash chỉ nhô lên 8–13 dB so với nền khi
có nhạc và giao tranh, so với hơn 60 dB trong phòng tập.

---

## 1. Ý tưởng ban đầu

- **Âm thanh làm trigger:** mỗi phép bổ trợ có tiếng riêng, giống nhau cho mọi người chơi và
  mọi skin. Nhận diện âm thanh liên tục rẻ hơn nhiều so với phân tích ảnh 60 khung/giây, và cho
  mốc thời gian chính xác cỡ 10–50 ms.
- **Ảnh làm quy kết:** khi nghe thấy tiếng, lấy ảnh màn hình quanh mốc đó (ring buffer) để biết
  tướng nào vừa dùng. Riêng kỹ năng tướng thì tiếng đã đủ cho biết tướng (mỗi tướng chỉ có một
  trong trận), nhưng phụ thuộc skin.

Đợt này chỉ đo **bước đầu tiên**: tiếng Flash có nhận ra được từ âm thanh hệ thống trong trận
thật hay không. Phần quy kết bằng ảnh chưa làm.

---

## 2. Môi trường

| Thành phần | Giá trị |
|---|---|
| Python | 3.10.11 |
| Thư viện | `pyaudiowpatch` (WASAPI loopback), `dxcam` (DXGI Desktop Duplication), `numpy` 1.26, `scipy` 1.11, `opencv-python` 4.13, `matplotlib` (chỉ cho script vẽ) |
| Thiết bị âm thanh | `Headphones (Realtek(R) Audio) [Loopback]`, 48 kHz, 2 kênh |
| Màn hình | 1920×1080, game chế độ Không viền (Borderless) |

```
pip install pyaudiowpatch dxcam numpy scipy opencv-python matplotlib
```

`ffmpeg` (chỉ để ghép video xem lại) cài qua scoop.

---

## 3. Công cụ

| File | Việc |
|---|---|
| [`common.py`](common.py) | Đọc WAV, log-mel spectrogram, đặc trưng delta, NCC trượt theo thời gian |
| [`record.py`](record.py) | Ghi một phiên: âm thanh loopback + ảnh màn hình + giờ game |
| [`make_template.py`](make_template.py) | Tạo mẫu từ bản ghi yên tĩnh có N lần dùng phép |
| [`detect.py`](detect.py) | Dò mẫu trên một phiên, xuất mốc + ảnh 3 khung quanh mỗi mốc |
| [`README.md`](README.md) | Hướng dẫn chạy từng bước |
| [`experiments/`](experiments/) | Các script phân tích một lần dùng trong đợt này (mục 7) |

### 3.1. `record.py`

```
python research/audio/record.py                       # âm thanh + 4 ảnh/giây + giờ game
python research/audio/record.py --no-screen           # chỉ âm thanh
python research/audio/record.py --seconds 60 --fps 30 # tự dừng, ảnh dày hơn
```

Ba luồng chạy song song, cùng mốc `t0 = perf_counter()` lúc bắt đầu:

- **Âm thanh:** callback của `pyaudiowpatch` ghi thẳng int16 vào `audio.wav`. WASAPI loopback
  **không trả dữ liệu khi hệ thống im lặng**, nên nếu thời gian thực vượt số mẫu đã ghi quá 0,1 s,
  callback chèn số 0 cho đủ. Nhờ vậy giây thứ t trong file luôn ứng với giây thứ t của phiên.
- **Ảnh:** `dxcam.grab()` liên tục, mỗi `1/fps` giây lưu một ảnh thu về 960×540 JPEG chất lượng 80,
  ghi `t,file` vào `frames.csv`.
- **Giờ game:** cứ 2 giây gọi `https://127.0.0.1:2999/liveclientdata/allgamedata`, ghi
  `t,gameTime` vào `game.csv`. Lần đầu kết nối được thì lưu cả JSON vào `allgamedata.json`
  (tướng, phép bổ trợ, phe của 10 người).

Dừng bằng Ctrl+C, hết `--seconds`, hoặc **tạo file rỗng `STOP` trong thư mục phiên** (dùng khi
chạy nền). Không kill tiến trình: luồng ảnh và CSV sẽ không được đóng gọn.

Dung lượng thực tế: 27 phút → WAV 300 MB, 6553 ảnh ~ 540 MB.

### 3.2. Đặc trưng âm thanh

1. **Log-mel:** STFT `n_fft=2048`, bước 480 mẫu (10 ms), 64 băng mel 100–12000 Hz, `log10`.
2. **Delta:** `F[:, t] = X[:, t] - X[:, t-3]`, tức là thay đổi so với 30 ms trước. Nhấn mạnh phần
   tấn công của âm thanh, bỏ phần nền ổn định.

Đã so 4 loại đặc trưng × 4 độ dài mẫu trên bản ghi phòng tập (script
[`experiments/feat_exp.py`](experiments/feat_exp.py)). "Biên" = điểm thấp nhất của Flash thật trừ
điểm cao nhất của đoạn không có Flash:

| Đặc trưng | Biên tốt nhất | Ghi chú |
|---|---|---|
| log-mel thô | 0,10 | Nền ổn định cũng tương quan cao với mẫu |
| log-mel kẹp sàn −8 | 0,10 | Không khác |
| trừ trung vị từng băng | 0,13 | Điểm thật cao nhưng nền cũng cao |
| **delta 30 ms** | **0,30** | Chọn dùng, mẫu dài 0,25 s |

### 3.3. NCC (normalized cross-correlation)

Mẫu `W` (64 × L khung) trượt trên đặc trưng `F` (64 × T). Tại mỗi vị trí:

```
ncc[t] = Σ (F[:, t:t+L] · Ŵ) / sqrt(var của cửa sổ × n)      Ŵ = W đã trừ trung bình, chuẩn hóa
```

Hai lỗi đã gặp và sửa:

- **Bùng nổ ở đoạn im lặng.** Bản đầu tính tổng và tổng bình phương của cửa sổ bằng
  `fftconvolve` float32. Ở đoạn im lặng phương sai thật ≈ 0, sai số làm tròn của FFT cho ra số
  âm hoặc cực nhỏ, NCC vọt lên 30–79. Sửa: tính tổng bằng `cumsum` float64, và đặt sàn độ lệch
  chuẩn `MIN_STD = 0.1` để cửa sổ gần như phẳng không bao giờ được coi là khớp.
- **Mẫu bị nhòe do onset lệch.** `make_template.py` tìm onset bằng năng lượng tăng vọt, nhưng
  đỉnh năng lượng lệch vài khung so với đỉnh của đặc trưng delta. Lấy trung vị các đoạn lệch nhau
  cho ra mẫu nhòe: 4/9 đoạn chỉ đạt 0,19–0,26 với chính mẫu đó. Sửa: căn từng đoạn theo mẫu sơ bộ
  (dịch tối đa ±50 ms tới vị trí NCC cao nhất), lấy lại trung vị, lặp 2 lần. Sau khi căn: 9/9 đoạn
  đạt 0,85–0,93.

Trước khi có dữ liệu thật, toán dò được kiểm bằng WAV tổng hợp
([`experiments/synth_test.py`](experiments/synth_test.py)): 6/6 "Flash" giả ở 4 mức biên độ được dò
đúng, 0 báo sai ở ngưỡng 0,45. Script này lưu mẫu `templates/synth_flash.npz`, xóa đi sau khi chạy.

---

## 4. Các phiên ghi

Tất cả trong [`sessions/`](sessions/), tên thư mục là giờ bắt đầu.

| Phiên | Nội dung | Kết quả dùng được |
|---|---|---|
| `20261019_171116` | Lần thử đầu trong Practice Tool, dừng giữa chừng | 47 s âm thanh, không dùng |
| `20261019_171210` | Lần thử thứ hai, dừng giữa chừng | 61 s âm thanh, không dùng |
| `20261019_171315` | **Ghi mẫu:** Practice Tool, đứng yên, Flash 9 lần, tắt nhạc | Mẫu `templates/flash.npz` |
| `20261019_171641` | **Thử báo sai:** 120 s đánh hình nộm, dùng kỹ năng, không Flash | Chỉ ~18 s có tiếng (xem 5.2) |
| `20261019_172345` | **Trận thật** 27,3 phút, Normal, ghi đủ âm thanh + ảnh 4 fps + giờ game | Ảnh, giờ game, điểm NCC, nhãn |

**Phiên trận thật không có `audio.wav` (300 MB) và `review.mp4` (243 MB) trong repo** vì vượt giới
hạn 100 MB/file của GitHub. Vẫn có:

- `frames/` + `frames.csv`: 6553 ảnh 960×540.
- `game.csv`: 785 mốc giờ game. Giờ game ≈ `t + 6` giây (bản ghi bắt đầu từ màn hình tải).
- `allgamedata.json`: đội hình. Phe ORDER (phe người ghi): Garen, Master Yi, Katarina, Kog'Maw,
  Lux. Phe CHAOS: Darius, Lee Sin, Zed, Kai'Sa, Yasuo. **Cả 10 người đều mang Flash.**
- `detect_flash/`: kết quả `detect.py` ngưỡng 0,5 (98 mốc, ảnh 3 khung mỗi mốc) và
  `scores.npy` (điểm NCC từng 10 ms của cả trận, đủ để thử ngưỡng khác mà không cần WAV).
- `labels.csv`: nhãn tay (mục 5.3). `labels_check/`: lưới 8 ảnh quanh mỗi nhãn.
- `own_flash_events.npy`: mốc suy từ HUD (mục 5.4, không đáng tin).

Tạo lại video xem lại (cần `audio.wav`):

```
ffmpeg -framerate 4 -i frames/%06d.jpg -i audio.wav -c:v libx264 -preset fast -crf 23 \
       -pix_fmt yuv420p -c:a aac -b:a 128k -shortest review.mp4
```

---

## 5. Kết quả

### 5.1. Phòng tập: mẫu nhất quán, tách khỏi nền rõ ràng

Mẫu `flash.npz`: 64 băng × 30 khung (0,05 s trước onset + 0,25 s sau). Dò lại trên chính phiên
`171315` ở ngưỡng 0,5: **9/9 đúng, 0 sai**, điểm 0,85–0,93. Nền: 99% khung dưới 0,28.

### 5.2. Thử báo sai: game tự tắt tiếng khi mất focus

Phiên `171641` dài 120 s nhưng 70 s đầu và 80–100 s hoàn toàn im lặng (RMS −180 dB). LMHT
**tắt âm thanh khi cửa sổ game mất focus** (Alt+Tab, click sang app khác). Trong ~18 s có tiếng:
99,9% khung dưới 0,42, cao nhất 0,66, là ba tiếng "tách" ngắn chưa xác định ở giờ game 5:28–5:42.

### 5.3. Trận thật: Flash lẫn vào nhiễu

`detect.py` ngưỡng 0,5 cho 98 mốc. Phân bố điểm của cả trận: trung vị −0,01, 99% 0,33,
99,9% 0,51, 99,99% 0,62, cao nhất 0,69. **Không có mốc nào đạt mức Flash ở phòng tập.**

Người chơi xem lại video và đánh dấu 6 lần Flash địch chắc chắn (danh sách chưa đầy đủ).
Đối chiếu bằng [`experiments/check_labels.py`](experiments/check_labels.py), cửa sổ −2 s / +3 s:

| Giờ game | Tướng | NCC cao nhất | RMS nền | RMS đỉnh |
|---|---|---|---|---|
| 3:23 | Yasuo | 0,44 | −21 dB | −13 dB |
| 5:19 | Lee Sin | 0,25 | −23 dB | −14 dB |
| 8:50 | Zed | 0,43 | −28 dB | −20 dB |
| 10:59 | Lee Sin | 0,61 | −26 dB | −13 dB |
| 15:27 | Darius | 0,54 | −28 dB | −16 dB |
| 18:50 | Zed | 0,35 | −25 dB | −13 dB |

Không có ngưỡng nào tách được: 0,5 bắt 2/6 kèm ~100 báo sai; 0,6 bắt 1/6.

### 5.4. Nguyên nhân

- **Nền liên tục ~ −25 dB có cấu trúc hòa âm** (vạch ngang rõ trên spectrogram, ví dụ quanh
  1059–1062 s). Đây là nhạc, và lớp này vẫn còn cả lúc người chơi Alt+Tab sang YouTube, nên ít
  nhất một phần đến từ trình duyệt. Chưa xác định phần nào là nhạc trong game.
- **Tỉ lệ tín hiệu/nền:** Flash trong trận chỉ cao hơn nền 8–13 dB, so với hơn 60 dB trong phòng tập.
  Mẫu học từ tiếng sạch nên không nhận ra tiếng đã trộn.
- **Alt+Tab:** trong trận có những đoạn người chơi chuyển sang trình duyệt, game tắt tiếng, ảnh
  chụp là desktop. Các đoạn này phải loại khỏi đánh giá.

### 5.5. Thử lấy mốc chuẩn từ HUD: không đáng tin

Ý tưởng: Flash của chính người chơi lúc nào cũng thấy trên HUD, ô D (Flash) sáng khi sẵn sàng, tối
khi hồi. Tìm khung chuyển sáng → tối thì có mốc chuẩn miễn phí.

Vùng ô D ở 960×540: `y 499:515, x 492:508`. Độ "vàng" `(R+G)/2 − B`: sẵn sàng ~42, đang hồi hoặc
không trong game < 30. Script [`experiments/own_flash.py`](experiments/own_flash.py) tìm 10 mốc
"sáng ổn định 2 s rồi tối ổn định 2 s". Điểm NCC tại các mốc đó: 0,15–0,54.

**Nhưng mốc không đúng:** xem ảnh ([`experiments/hud_crop.py`](experiments/hud_crop.py) phóng to
HUD) thì ở nhiều mốc ô D đang hiện số đếm ngược, tức Flash đã hồi từ trước, còn cú "chuyển tối"
thực ra là màn hình chết (HUD xám) hoặc Alt+Tab. Cần thêm điều kiện (thanh máu > 0, vòng cấp độ
hiện, không có số trên ô D) mới dùng được.

---

## 6. Những điều đã xác minh

**Nguồn dữ liệu trong trận:**

- Live Client Data API: có tướng, phép bổ trợ, trang bị, level, ngọc, `skinID` của 10 người.
  `/eventdata` chỉ có hạ gục, trụ, rồng, baron, ace... **Không có sự kiện dùng phép**, không có
  thời gian hồi của người khác.
- Overwolf GEP: sự kiện `abilities` chỉ của người chơi hiện tại, và không có sự kiện phép bổ trợ.
- Khung mục tiêu (click chọn tướng địch): **không** hiện thời gian hồi của địch.
- Khung đồng đội bên trái: hiện thời gian hồi phép bổ trợ và R của đồng đội.

**Âm thanh:**

- Phép bổ trợ: một bộ âm thanh chung cho mọi tướng và mọi skin, nên một mẫu Flash là đủ.
  Nhưng tiếng Flash của 10 người giống hệt nhau, âm thanh không cho biết ai dùng.
- Kỹ năng tướng: skin Epic trở lên thường có âm thanh riêng; cần mẫu theo skin (biết trước được
  nhờ `skinID` trong Live API). Một kỹ năng có nhiều tiếng (cast, trúng, kết thúc, tái kích hoạt).
- **Process loopback** (Windows 10 2004+, `ActivateAudioInterfaceAsync` với
  `AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK`) thu riêng âm thanh của một tiến trình, loại được
  Discord, trình duyệt, nhạc ngoài. Không loại được nhạc *trong* game vì cùng tiến trình. Các thư
  viện Python phổ biến chưa bọc API này; cần helper C++ (mẫu `ApplicationLoopback` của Microsoft)
  hoặc tự làm COM interface bằng `comtypes`.

**Hình ảnh (quan sát trên ảnh 4 fps của trận):**

- Ở mốc 3:23 (Yasuo), vệt sáng vàng của Flash thấy được trong 2 khung liên tiếp.
- Ở mốc 10:59 (Lee Sin), không chỉ ra được Flash trong 8 khung: lẫn với Q của Lee Sin, chữ
  "+405" vàng, chữ "LÊN CẤP", ping.
- Để biết *ai* Flash qua ảnh cần 30–60 fps (thấy thanh máu nhảy cóc giữa hai khung), quy vị trí
  trên màn hình về minimap bằng khung camera trắng, và loại các kỹ năng lướt có tầm tương tự.

**Sau trận:**

- File replay `.rofl`: phần metadata JSON chỉ có thống kê cuối trận. Phần payload là luồng gói
  tin (giống luồng spectator) có đủ mọi lần dùng phép nhưng mã hóa Blowfish, định dạng chỉ được
  cộng đồng dịch ngược một phần cho phiên bản cũ.
- Match-V5 timeline: hạ gục, mua đồ, lên cấp, cắm mắt, mục tiêu lớn. Không có lần dùng phép.
- Khi xem replay trong client, chọn bất kỳ tướng nào (kể cả địch) thì HUD hiện kỹ năng và phép
  bổ trợ của tướng đó kèm đếm ngược.
- Replay API (`https://127.0.0.1:2999/replay/...`): `/replay/playback` tua, đặt tốc độ, đọc `time`
  chính xác; `/replay/render` có `selectionName` để chọn tướng. Replay chỉ mở được khi client còn
  cùng patch với trận.

---

## 7. Script thử nghiệm

Trong [`experiments/`](experiments/). Chạy từ **thư mục gốc project** (chúng thêm `research/audio`
vào `sys.path` theo đường dẫn tương đối).

| Script | Việc | Ví dụ |
|---|---|---|
| `synth_test.py` | Kiểm toán dò bằng WAV tổng hợp | `python research/audio/experiments/synth_test.py <thư mục tạm>` |
| `diag.py` | Vẽ RMS + log-mel + NCC của một đoạn | `python .../diag.py <phiên> flash out.png 100 121` |
| `feat_exp.py` | So các loại đặc trưng và độ dài mẫu | `python .../feat_exp.py research/audio/sessions/20261019_171315` |
| `hud_crop.py` | Phóng to vùng HUD kỹ năng, kẻ lưới tọa độ | `python .../hud_crop.py <phiên>/frames out.png 003405 001000` |
| `own_flash.py` | Mốc Flash của người chơi từ ô D trên HUD | `python .../own_flash.py <phiên> flash` |
| `check_labels.py` | Đối chiếu `labels.csv` với NCC, xuất lưới ảnh | `python .../check_labels.py <phiên>` |

`diag.py`, `own_flash.py` và `check_labels.py` cần `audio.wav` của phiên (hoặc `scores.npy` với
`own_flash.py`).

---

## 8. Câu hỏi còn bỏ ngỏ

1. **Nhạc trong game hay nhạc ngoài?** Ghi lại với nhạc game = 0 và không mở gì khác, xem lớp nền
   hòa âm còn không. Cách nhanh nhất là ghi âm thanh lúc xem replay của chính trận
   `20261019_172345` (cùng patch) rồi đối chiếu với 6 nhãn sẵn có.
2. **Không có nhạc thì Flash có nhô lên khỏi tiếng giao tranh không?** Nếu vẫn chỉ ~0,4 tại 6 nhãn
   thì so mẫu đơn không đủ, cần mô hình học từ nhiều mẫu có nhãn.
3. **Ba tiếng "tách" ở 5:28–5:42** trong phiên `171641` là gì.
4. **Nhãn đầy đủ:** danh sách hiện tại chỉ có 6 Flash địch. Đánh dấu thêm (cả Flash của mình và
   đồng đội, cả lần chỉ nghe thấy ngoài màn hình) theo định dạng `labels.csv`:
   ```
   gameTime,champion,team,note
   3:23,Yasuo,enemy,
   14:17,Lee Sin,enemy,ngoài màn hình
   ```
