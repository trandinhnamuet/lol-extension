# Nghiên cứu: nhận ra tiếng Tốc Biến (Flash) từ âm thanh game

Ghi lại toàn bộ những gì đã làm, đo được và còn bỏ ngỏ trong đợt thử nghiệm ngày 19/10/2026,
để có thể tiếp tục trên máy khác. Code nằm trong thư mục này, tách hẳn khỏi app chính
([`spell_timer.py`](../../spell_timer.py) không bị sửa).

**Kết luận ngắn:** trong Practice Tool, so mẫu âm thanh nhận ra Flash gần như hoàn hảo
(9/9, điểm 0,85–0,93, nền ≤ 0,42). Trong một trận thật 27 phút, cùng phương pháp **không tách
được Flash khỏi nhiễu**: 6 lần Flash địch được gắn nhãn tay chỉ đạt 0,25–0,61, trong khi nhiễu
nền lên tới 0,69. Nguyên nhân chính đo được là tiếng Flash chỉ nhô lên 8–13 dB so với nền khi
có nhạc và giao tranh, so với hơn 60 dB trong phòng tập.

**Bổ sung 19/10 (tối), đo trên replay, mục 9:** tắt hẳn nhạc, camera gắn vào tướng của người
chơi, mốc chuẩn lấy tự động từ HUD replay cho cả 10 người (21 lần Flash trong 19 phút). Kết quả
vẫn thế: 21 lần Flash đạt NCC 0,23–0,87 (trung vị 0,43), nền 99,9% = 0,59. **Khoảng cách không
phải nguyên nhân**: 15 lần Flash trong tầm 1000 đơn vị quanh camera chỉ 5 lần vượt 0,5. Trận thứ hai (27 phút, 37 Flash) cho đúng kết quả đó: ngưỡng 0,5 bắt 8/37 với 44 báo sai / 10
phút. Flash hầu như luôn dùng giữa giao tranh, tiếng bị tiếng chiến đấu lấn. So mẫu đơn không đủ; cái thu được là
**quy trình tự động tạo dữ liệu có nhãn từ replay** để huấn luyện mô hình thật.

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

---

## 9. Đo trên replay: mốc chuẩn tự động cho cả 10 người (19/10, tối)

Làm trên máy khác (Python 3.10.6, tài khoản `SRV TranKhoaCu#ICS`, server VN2). Lịch sử đấu của
tài khoản này toàn ranked patch 16.20, trùng patch client nên mở replay được; trận
`20261019_172345` không có ở đây. Mục tiêu: trả lời câu hỏi 1 và 2 của mục 8 (không nhạc thì sao,
có phải vì xa camera không) mà không cần chơi và không cần gắn nhãn tay.

### 9.1. Công cụ mới

| File | Việc |
|---|---|
| [`replay_session.py`](replay_session.py) | Tải replay qua LCU, mở, gắn camera vào tướng của người chơi, phát 1x và ghi phiên (âm thanh + ảnh + giờ game + `replay.csv`) tới hết trận |
| [`hud_flash.py`](hud_flash.py) | Đọc ô Flash của 10 người từ hai cột khung tướng của HUD replay → `flash_events.csv` |
| [`replay_positions.py`](replay_positions.py) | Mở lại replay, lần lượt gắn camera vào từng tướng mỗi 0,2 s, đọc `cameraPosition` → vị trí 10 tướng theo thời gian |
| [`compare_hud_audio.py`](compare_hud_audio.py) | Với mỗi Flash (HUD): NCC cao nhất trong [−1,5 s, +0,5 s], RMS; bắt/sót/báo sai theo ngưỡng |
| [`flash_distance.py`](flash_distance.py) | Ghép khoảng cách Flash → camera vào bảng trên |
| [`train_classifier.py`](train_classifier.py) | Thử logistic regression trên cửa sổ delta log-mel thay cho NCC |

Những điều phải biết để chạy lại:

- **Replay API** (`https://127.0.0.1:2999/replay/playback`, `/replay/render`) mặc định tắt. Bật
  bằng `EnableReplayApi=1` trong `[General]` của `game.cfg`; làm qua LCU để client không ghi đè:
  `PATCH /lol-game-settings/v1/game-settings {"General":{"EnableReplayApi":true}}` rồi
  `POST /lol-game-settings/v1/save`. Tắt nhạc cũng bằng cách đó (`{"Volume":{"MusicMute":true}}`).
  Live Client Data (`/liveclientdata/*`) thì chạy sẵn trong replay, chỉ `activePlayer` báo
  "Spectator mode doesn't currently support this feature".
- Tải replay: `POST /lol-replays/v1/rofls/{gameId}/download` body
  `{"componentType":"replay-button_match-history"}`, chờ `GET /lol-replays/v1/metadata/{gameId}`
  có `state: "watch"` (vài giây). Mở: `POST /lol-replays/v1/rofls/{gameId}/watch` cùng body.
- `POST /replay/render {"selectionName": <riotIdGameName>, "cameraAttached": true}` gắn camera vào
  tướng; `selectionName` nhận **tên người chơi (phần trước dấu #)**, không nhận tên tướng.
  `cameraPosition` trả về lúc đó chính là vị trí tướng (dùng cho `replay_positions.py`).
- Lúc game còn đang tải, `POST /replay/playback {"paused": false}` bị bỏ qua: phải gửi lại cho
  tới khi `time` chạy. `speed: 2` cũng chỉ có hiệu lực sau lúc đó.
- Lúc mới vào, `allgamedata` chỉ có 1–2 người; chờ đủ 10 rồi mới lưu.
- Git Bash đổi `/lol-...` thành đường dẫn Windows khi truyền vào lệnh: đặt `MSYS_NO_PATHCONV=1`.
  Console Windows cần `PYTHONUTF8=1` để in tiếng Việt.

### 9.2. Mốc chuẩn từ HUD replay

HUD replay có hai cột khung tướng (5 ORDER bên trái, 5 CHAOS bên phải) hiện **hai phép bổ trợ và
R của từng người**, kể cả địch trong sương mù. Ô Flash sáng vàng khi sẵn sàng; khi dùng, ô tối đi
và lớp phủ hồi chiêu là vòng quét nên độ vàng tăng tuyến tính trở lại trong ~5 phút. Ở ảnh
960×540: cột trái x 5:11, cột phải x 949:955, hàng đầu y 80:88, cách nhau 51 px, phép 2 cách
phép 1 11 px. Thứ tự hàng = thứ tự `allPlayers`, ô nào là Flash lấy từ `summonerSpells`.

Độ vàng `(R+G)/2 − B`: sẵn sàng 68–78, đang hồi 20–25 **nhưng dao động theo nền game vì lớp phủ
bán trong suốt**, nên dùng ngưỡng kép (sẵn sàng > 50, hồi < 35, mỗi trạng thái ổn định 4 khung).
Ngưỡng đơn 25 cho ra Flash giả cách nhau 30 s. Cuối trận cả HUD tối cùng lúc → bỏ mốc nào có ≥ 3
người cùng "Flash" trong 1 s. Kết quả trận `1609077581` (19,2 phút, Akshan của người chơi): **21
lần Flash**, khoảng cách giữa hai lần của cùng người đều ≥ 313 s (hợp với hồi chiêu 300 s). Đã xem
lại ảnh ở 3 mốc có NCC thấp nhất: đều đúng.

### 9.3. Kết quả âm thanh (không nhạc, camera gắn vào tướng của người chơi)

Phiên `sessions/replay_1609077581_20261019_204709` (WAV 221 MB không đưa lên GitHub; có
`detect_flash/scores.npy`, `flash_events.csv`, `compare_flash.csv`, `flash_distance.csv`,
`hud_yellow.png`).

Phân bố NCC cả phiên: 99% 0,34; 99,9% 0,59; 99,99% 0,71; cao nhất 0,87 (và đó là một Flash).

| Ngưỡng | Bắt được /21 | Báo sai | Báo sai / 10 phút |
|---|---|---|---|
| 0,4 | 11 | 312 | 163 |
| 0,5 | 8 | 145 | 76 |
| 0,6 | 1 | 61 | 32 |
| 0,7 | 1 | 9 | 4,7 |

Khoảng cách Flash → camera (từ `replay_positions.py`, vị trí nội suy, sai số ±2 s di chuyển):

| Cách (đơn vị bản đồ) | Số lần | NCC trung vị | ≥ 0,5 |
|---|---|---|---|
| 0–1000 (trên màn hình) | 15 | 0,43 | 5 |
| 1000–2000 | 3 | 0,60 | 3 |
| > 2000 | 3 | 0,29 | 0 |

Ba lần Flash của chính Akshan (cách 0): 0,59 / 0,54 / 0,27. Lần đạt 0,87 (Graves 17:34) là lần
duy nhất nền yên tĩnh (−55 dB ngay trước): tiếng Flash sạch thì mẫu khớp như trong phòng tập.
Các lần còn lại đều nằm giữa giao tranh (xem `hud_yellow.png`: các mốc gom thành cụm 5:01–5:27,
10:56–11:04, 17:07–17:34), RMS chỉ nhô 5–9 dB. Những đỉnh NCC 0,7–0,83 không phải Flash là tiếng
kỹ năng lướt / va chạm trong giao tranh (đã kiểm tra HUD của cả 10 người quanh 7 đỉnh cao nhất:
không ai đổi trạng thái).

Trả lời mục 8: (1) nền hòa âm trong trận trước là nhạc (giờ tắt nhạc thì hết), nhưng (2) không
có nhạc Flash vẫn không nhô lên khỏi tiếng giao tranh, và (3) không phải vì xa camera.

### 9.4. Trận thứ hai xác nhận: `1608903464` (27,5 phút, Vladimir, ranked)

Phiên `sessions/replay_1608903464_20261019_211904`, cùng cách làm. HUD cho **37 lần Flash** (các
khoảng cách giữa hai lần của cùng người đều ≥ 314 s). NCC cả phiên: 99,9% 0,52; cao nhất 0,78.

| Ngưỡng | Bắt được /37 | Báo sai | Báo sai / 10 phút |
|---|---|---|---|
| 0,4 | 14 | 318 | 116 |
| 0,5 | 8 | 122 | 44 |
| 0,6 | 3 | 37 | 13,5 |
| 0,7 | 2 | 7 | 2,5 |

Flash của chính Vladimir (camera gắn vào): 0,59 / 0,46 / 0,28 / 0,18 / (27:06 ngoài WAV). Lần
22:57 chỉ 0,18 dù ở ngay camera, nền −18 dB: giao tranh cuối trận.

Khoảng cách Flash → camera (`positions_1608903464_20261019_214657`):

| Cách (đơn vị bản đồ) | Số lần | NCC trung vị | ≥ 0,5 |
|---|---|---|---|
| 0–1000 (trên màn hình) | 27 | 0,32 | 5 |
| 1000–2000 | 5 | 0,31 | 1 |
| > 2000 | 5 | 0,43 | 2 |

27/37 lần Flash ở ngay trên màn hình mà chỉ 5 lần vượt 0,5: khẳng định lại khoảng cách không phải
nguyên nhân.

### 9.5. Thử bộ phân loại tuyến tính

`train_classifier.py`, logistic regression L2 trên cửa sổ 64×30 delta log-mel, dương = Flash
± 2 khung, âm = 3000 cửa sổ ngẫu nhiên + ~700 đỉnh NCC giả, cân bằng lớp.

- Leave-one-out trên trận 1: 18/21 Flash giữ lại được chấm p ≥ 0,7, nhưng quét lại cả trận ở
  p ≥ 0,99 vẫn 75 báo sai (39 / 10 phút).
- **Huấn luyện trận 1, kiểm tra trận 2** (không trộn trận):

| Ngưỡng p | Bắt được /37 | Báo sai / 10 phút |
|---|---|---|
| 0,90 | 23 | 94 |
| 0,95 | 17 | 60 |
| 0,99 | 6 | 21 |

Tốt hơn NCC ở cùng mức báo sai (NCC 0,4: 14/37 với 116 báo sai / 10 phút) nhưng còn xa mức dùng
được. Mô hình tuyến tính trên đặc trưng này không đủ; cần mô hình phi tuyến (CNN nhỏ trên log-mel)
và nhiều trận hơn 1 trận huấn luyện.

### 9.6. CNN nhỏ trên log-mel: tín hiệu đầu tiên (20/10, 2 trận)

[`train_cnn.py`](train_cnn.py): cửa sổ 1 s log-mel (64 × 100, chuẩn hóa từng băng theo trung vị /
IQR của phiên), dương nếu cửa sổ chứa trọn [t_HUD − 0,6 s, t_HUD + 0,1 s] (không cần căn onset),
âm nếu cách mọi mốc > 1,5 s; 4 lớp conv + global max pool (tự tìm onset trong cửa sổ), ~60k tham
số, 12 epoch. Dò bằng trượt bước 0,05 s, đỉnh cách nhau ≥ 1 s, đúng nếu cách t_HUD − 0,35 ≤ 1 s.

Leave-one-match-out với 2 trận:

| Huấn luyện → kiểm tra | p ≥ 0,5 | p ≥ 0,9 | p ≥ 0,95 |
|---|---|---|---|
| 37 Flash (trận 2) → trận 1 (21 Flash) | 11/21, 26 báo sai/10 ph | 6/21, 6,3/10 ph | 4/21, 2,6/10 ph |
| 21 Flash (trận 1) → trận 2 (37 Flash) | 1/37, 0 báo sai | 0/37 | 0/37 |

Chiều có 37 Flash huấn luyện đã hơn hẳn NCC ở cùng mức báo sai (NCC 0,5 trên trận 1: 8/21 với 76
báo sai / 10 phút). Chiều ngược lại sụp hẳn: 21 mốc là quá ít. Dữ liệu là nút thắt, đúng như dự
đoán, nên đang ghi hàng loạt ([`replay_batch.py`](replay_batch.py), 16 trận ranked gần nhất, chỉ
lưu hai cột HUD, nhật ký `sessions/batch.log`); khi xong, một tiến trình chờ sẵn sẽ chạy
`train_cnn.py --cv` trên mọi phiên và ghi `sessions/cnn_cv.log`.

**Cập nhật 04:30 ngày 20/10, 7 trận (259 Flash, 191 phút), leave-one-match-out** (`sessions/cnn_cv_7.log`):

| Ngưỡng p | Bắt được /259 | Báo sai | Báo sai / 10 phút |
|---|---|---|---|
| 0,50 | 212 (82%) | 175 | 9,1 |
| 0,70 | 204 (79%) | 106 | 5,5 |
| 0,90 | 188 (73%) | 36 | 1,9 |
| 0,95 | 179 (69%) | 29 | 1,5 |
| 0,98 | 166 (64%) | 17 | 0,9 |

Từng trận ở p ≥ 0,9 bắt 62–87%, báo sai 0,8–3,6 / 10 phút; trận 19 phút đầu tiên (nền khác, Akshan)
là trận kém nhất. So với 2 trận: cùng mức ~2 báo sai / 10 phút, tỉ lệ bắt tăng từ 29% lên 73%. Mẫu
số 259 gồm cả Flash xa camera, nên trần thực tế dưới 100%; muốn biết trần cần ghép thêm vị trí
(`replay_positions.py`) để chỉ tính Flash trong tầm nghe.

**Cập nhật 11:30 ngày 20/10, 17 trận (655 Flash, 469 phút), leave-one-match-out** (`sessions/cnn_cv.log`,
mô hình học từ 17 trận lưu ở `models/flash_cnn.pt`):

| Ngưỡng p | Bắt được /655 | Báo sai | Báo sai / 10 phút |
|---|---|---|---|
| 0,50 | 541 (83%) | 474 | 10,1 |
| 0,90 | 506 (77%) | 153 | 3,3 |
| 0,95 | 496 (76%) | 103 | 2,2 |
| 0,98 | 479 (73%) | 62 | 1,3 |

So với 7 trận: ở cùng mức ~1,3 báo sai / 10 phút, tỉ lệ bắt tăng từ 64% lên 73%. Từng trận ở
p ≥ 0,98 bắt 67–87% (trừ trận dưới), báo sai 0–3,2 / 10 phút. Chưa đạt 90% / ≤ 1, nhưng vẫn tăng
theo dữ liệu, và mẫu số gồm cả Flash xa camera (chưa đo trần).

**Hai trận hỏng vì máy bị dùng trong lúc ghi** (game mất focus thì tắt tiếng, kể cả khi cửa sổ
khác ở màn hình thứ hai và game vẫn hiện trên ảnh):
- `broken_replay_1608773098_20261020_035201`: từ phút 7,5 ảnh là cửa sổ VS Code, HUD mất, 10 Flash.
- `broken_replay_1608773098_20261020_101135` (ghi lại lúc 10:11): HUD đủ 42 Flash nhưng 17/42 rơi
  vào đoạn âm thanh −53…−57 dB, năng lượng log-mel trung bình −7,8 so với −5,3 ở phiên tốt; mô hình
  học từ 17 trận chỉ bắt 3/42. Cả hai đã đổi tên `broken_` để glob `replay_*` bỏ qua.
- `replay_1608756021_20261020_041938` (ghi 04:19–04:37) bị một phần: 8/24 Flash trong đoạn im lặng,
  CNN bắt 4/24. Vẫn nằm trong bảng trên; bỏ nó ra thì p ≥ 0,98 bắt 75%, 1,35 báo sai / 10 phút.

Quy tắc ghi: để máy yên hoàn toàn trong lúc batch chạy, không gõ, không click. Kiểm tra nhanh sau
mỗi trận: 20 đoạn RMS rải đều phải đều ở −20…−30 dB, không đoạn nào dưới −45 dB.

**Cải tiến 15:00 ngày 20/10: kênh delta + hard-negative mining** (`train_cnn.py --mine`,
`sessions/cnn_cv_mine8.log`). Đầu vào 2 kênh (log-mel và delta 30 ms); huấn luyện 2 giai đoạn, giai
đoạn 2 thêm "âm khó" = các đỉnh p ≥ 0,3 không gần mốc HUD trên chính phiên huấn luyện (tối đa 400
đỉnh/phiên, mỗi đỉnh 5 cửa sổ dịch ±10 khung). So sánh trên cùng 8 trận (334 Flash, 234 phút):

| Ngưỡng p | Cũ: bắt | Cũ: báo sai / 10 ph | Mới: bắt | Mới: báo sai / 10 ph |
|---|---|---|---|---|
| 0,90 | 258 (77%) | 3,0 | 260 (78%) | 1,4 |
| 0,95 | 252 (75%) | 2,1 | 256 (77%) | 1,0 |
| 0,98 | 243 (73%) | 1,3 | 249 (75%) | 0,6 |

Báo sai giảm một nửa ở mọi ngưỡng, tỉ lệ bắt không giảm. Mức ≤ 1 báo sai / 10 phút đã đạt ở
p ≥ 0,95 với 77% bắt. Phần bắt còn thiếu phải đối chiếu với trần theo khoảng cách (mục dưới).

**Trần theo khoảng cách (15:20 ngày 20/10, `cnn_ceiling.py`, mô hình cũ, p ≥ 0,98, 3 trận có vị trí):**

| Cách camera | Số Flash | Bắt được |
|---|---|---|
| 0–1000 (trên màn hình) | 93 | 74 (80%) |
| 1000–2000 | 11 | 8 (73%) |
| > 2000 | 9 | 7 (78%) |

Flash xa camera vẫn bắt được gần như xa gần như nhau: game phát tiếng Flash không phụ thuộc
khoảng cách (ít nhất trong replay). **Không có trần vật lý đáng kể**; các lần sót nằm ngay cạnh
camera trong giao tranh đông, tức là tiếng bị chồng lấn, đó là giới hạn của mô hình chứ không
phải của loa. Hai trận ghi lại (1608773098: 42 Flash, 1608756021: 24 Flash) đều lành, đã đưa vào
tập 19 trận; `sessions/cnn_cv_mine_all.log` là kiểm chéo đầy đủ với mô hình mới.

**Kết quả đầy đủ 19:30 ngày 20/10: 18 trận sạch (697 Flash, 515 phút), kênh delta + hard-negative,
leave-one-match-out** (`sessions/cnn_cv_mine_all.log`):

| Ngưỡng p | Bắt được /697 | Báo sai | Báo sai / 10 phút |
|---|---|---|---|
| 0,50 | 576 (83%) | 271 | 5,5 |
| 0,90 | 557 (80%) | 84 | 1,7 |
| 0,95 | 552 (79%) | 55 | 1,1 |
| 0,98 | 538 (77%) | 36 | 0,7 |

Từng trận ở p ≥ 0,95: bắt 58–89%, báo sai 0,3–2,5 / 10 phút. Hai trận ghi lại (1608773098: 35/42,
1608756021: 14/24) nằm trong bảng. Điểm xuất phát sáng 19/10 là NCC: 8/21 với 76 báo sai / 10 phút.

### 9.7. Tích hợp vào app (21/10)

Mô hình xuất sang ONNX (`research/audio/export_onnx.py` → `models/flash_cnn.onnx`, sai lệch logit
so với PyTorch < 1e-4). `flash_listener.py` chạy đúng đường streaming (ring buffer, log-mel numpy,
chuẩn hóa chạy 120 s): đưa `audio.wav` của một phiên qua đường này (`test_listener_offline.py`)
cho kết quả tương đương bản offline, tốn 4,8% thời gian thực trên 1 luồng. Quy kết "ai Flash" bằng
minimap (`minimap_tracker.py`, xem TECHNICAL.md mục 12). Bài thử thật: chạy app trong lúc xem
replay, đối chiếu `auto_flash.log` với HUD bằng `compare_auto_log.py`.

**Ba bài thử thật bằng replay (21/10, 01:20–02:47, app chạy nổi trong lúc xem replay, đối chiếu
`auto_flash.log` với HUD):**

| Bài | Trận | Flash "địch" theo app | Nghe thấy | Ghi chú |
|---|---|---|---|---|
| 1 | 1608903464 (8 phút đầu) | 3 | 2 | minimap lỗi (vùng đồng màu → inf), chỉ đo âm thanh |
| 2 | 1609046506, 36,7 phút | 29 | 24 (83%) | khớp chân dung trong vòng đỏ, bản đầu: tự bấm đúng 13, sai 1, không căn cứ 3, hỏi 10 |
| 3 | 1602364327, 35,7 phút | 24 | 18 (75%) | bản đầu: đúng 10, sai 2, không căn cứ 6; **chấm lại trên vết đã ghi với quy tắc cuối: đúng 10, sai 0, không căn cứ 0, hỏi 8** |

Quy tắc cuối (`minimap_tracker.who_jumped`): cú nhảy 5–12 px (Flash 400 đơn vị ≈ 7 px; đo thật
6–10 px) trong ≤ 0,25 s, xảy ra trong [−0,1 s, +0,4 s] quanh mốc tiếng (đo thật +0,08…+0,31 s), icon
đứng yên ±4,5 px trong 0,3 s trước và ở lại chỗ mới sau. Bỏ "đứng yên trước" thì nhầm danh tính 1–2
khung (bước 22–95 px) thành Flash; bỏ giới hạn cửa sổ thì kỹ năng lướt (Pyke E, Lucian E, Azir E)
trùng tiếng Flash của người khác bị bấm nhầm. Các lần "hỏi" còn lại là icon chồng nhau / mất dấu
(Graves NCC chỉ 0,25–0,31) hoặc cú nhảy đọc được 4–4,5 px dưới ngưỡng.

### 9.8. Việc tiếp theo

1. Âm thanh: tăng tỉ lệ bắt trong giao tranh (còn ~20% sót): huấn luyện lại với 26 trận đã có,
   augmentation trộn tiếng Flash sạch vào nền giao tranh, kênh delta đã có; nghe thử 20 "sót" bằng tai
   (`export_clips.py`).
2. Minimap: theo dõi vòng (track) kể cả khi chân dung không nhận ra (giữ danh tính theo vị trí),
   để không mất Graves/icon chồng nhau; thử ngưỡng nhảy 4,5 px với điều kiện ở lại chặt hơn.
3. Thử trong trận thật (không phải replay): sương mù làm icon địch ẩn/hiện, và tiếng Discord/nhạc.
3. Khi đạt: xuất mô hình, dò thời gian thực trên loopback (cửa sổ trượt 1 s, trễ ~0,5 s), rồi
   mới làm bước quy kết "ai Flash" bằng ảnh.
3. Cùng dữ liệu đó có thể gắn nhãn Ignite/Heal/Exhaust/Barrier (HUD hiện cả phép thứ hai) và R.
