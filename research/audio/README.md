# Bài đo: nhận ra tiếng phép bổ trợ từ âm thanh hệ thống

Mục tiêu: trả lời "tiếng Flash có nhận ra được từ loopback, trong trận thật, với tỉ lệ bao nhiêu?"
trước khi xây hệ thống lớn. Không đụng vào app chính.

Kết quả, phân tích và các câu hỏi còn bỏ ngỏ: xem [RESEARCH.md](RESEARCH.md).

Cần: `pip install pyaudiowpatch dxcam numpy scipy opencv-python` (đã cài).
Game để chế độ **Không viền (Borderless)**. Trong cài đặt âm thanh của game: bật hiệu ứng, tắt nhạc.

## Bước 1: ghi mẫu (Practice Tool)

1. Vào Practice Tool, chọn tướng có Flash. Tắt nhạc game, tắt Discord/nhạc ngoài.
2. Chạy:
   ```
   python research/audio/record.py --no-screen
   ```
3. Đứng yên, không đánh gì, bấm Flash **8 lần**, mỗi lần cách nhau ít nhất 3 giây
   (Practice Tool có nút đặt lại hồi chiêu). Xong bấm Ctrl+C.
4. Tạo mẫu:
   ```
   python research/audio/make_template.py research/audio/sessions/<phiên>/audio.wav --name flash --count 8
   ```
   NCC của từng đoạn với mẫu nên > 0.7. Nếu một đoạn thấp hẳn, có thể onset bắt nhầm tiếng khác.
5. Thử dò ngay trên chính bản ghi đó để xem điểm của Flash thật so với nền:
   ```
   python research/audio/detect.py research/audio/sessions/<phiên> --template flash --thr 0.4
   ```

Làm tương tự cho Ignite, Heal, Exhaust... nếu muốn (`--name ignite`).

## Bước 2: đo trong trận thật

1. Trước khi vào trận (hoặc đang trong trận):
   ```
   python research/audio/record.py
   ```
   Ghi âm thanh + 4 ảnh màn hình/giây + giờ game. ~30 phút tốn ~350MB WAV và ~150MB ảnh.
2. Chơi bình thường. Hết trận bấm Ctrl+C (hoặc tạo file rỗng tên `STOP` trong thư mục phiên,
   dùng khi chạy nền). Đừng kill tiến trình: file WAV sẽ không có header.
   Lưu ý: game tắt tiếng khi mất focus, nên đừng Alt+Tab lúc đang đo.
3. Dò:
   ```
   python research/audio/detect.py research/audio/sessions/<phiên> --template flash --thr 0.5
   ```
4. Mở thư mục `detect_flash/`: mỗi lần dò được có một ảnh gồm 3 khung (trước 0,5s | lúc dò | sau 0,5s).
   Đánh dấu từng cái là **đúng** (thấy Flash trên màn hình, kể cả của mình/đồng đội) hay **sai**.
5. Nếu nhớ được vài lần Flash mà không được dò, ghi lại giờ game để đo tỉ lệ bỏ sót.

## Đọc kết quả

- `NCC nền 99.99%` là điểm cao nhất mà tiếng linh tinh trong trận đạt được. Flash thật cần cao hơn
  mức này rõ rệt thì mới có ngưỡng dùng được.
- Thử các `--thr` khác nhau trên cùng phiên (không cần ghi lại), `scores.npy` có điểm từng 10ms.
- Mục tiêu để đi tiếp: Flash trong tầm camera được dò ≥ 90%, báo sai ≤ 1 lần / 10 phút.

## Bước 3 (khuyên dùng): đo bằng replay, mốc chuẩn tự động

Không cần chơi, không cần gắn nhãn tay: HUD replay hiện phép bổ trợ của cả 10 người. Cần client
đang đăng nhập, replay cùng patch, và một lần bật Replay API + tắt nhạc qua LCU (xem mục 9.1
của [RESEARCH.md](RESEARCH.md)). Đặt `PYTHONUTF8=1`; trong Git Bash thêm `MSYS_NO_PATHCONV=1`.

```
python research/audio/replay_session.py --list                       # lịch sử đấu, lấy gameId
python research/audio/replay_session.py <gameId> --kill              # tải + mở + ghi tới hết trận (1x)
python research/audio/replay_positions.py <gameId> --speed 2 --kill  # lượt 2: vị trí 10 tướng
python research/audio/detect.py research/audio/sessions/replay_<gameId>_<t> --template flash --thr 0.4
python research/audio/hud_flash.py research/audio/sessions/replay_<gameId>_<t> --plot
python research/audio/compare_hud_audio.py research/audio/sessions/replay_<gameId>_<t>
python research/audio/flash_distance.py research/audio/sessions/replay_<gameId>_<t> research/audio/sessions/positions_<gameId>_<t>
```

Đừng click sang cửa sổ khác trong lúc ghi (game tắt tiếng khi mất focus). `audio.wav` của một
trận 20–30 phút nặng 200–350 MB, không đưa lên git.

## Bước 4: ghi hàng loạt và huấn luyện CNN

```
python research/audio/replay_batch.py --from-history --min-minutes 15     # mọi trận cùng patch trong lịch sử
python research/audio/replay_batch.py 1608862888 1608842566 ...           # hoặc danh sách gameId
```

Mỗi trận: tải, mở, ghi âm thanh + hai cột HUD (`--hud-only`, ~15 MB ảnh thay vì 500 MB) + giờ
game, rồi `hud_flash.py` → `flash_events.csv`. Nhật ký `sessions/batch.log`; tạo file
`sessions/BATCH_STOP` để dừng sau trận hiện tại. Thêm `--positions` nếu cần vị trí tướng.

```
pip install torch --index-url https://download.pytorch.org/whl/cu121
python research/audio/train_cnn.py --cv research/audio/sessions/replay_*          # leave-one-match-out
python research/audio/train_cnn.py --train <các phiên> --test <phiên khác> --save  # lưu models/flash_cnn.pt
```

`train_cnn.py` không cần căn onset: cửa sổ 1 s là dương nếu chứa mốc HUD − 0,6…+0,1 s. Thêm
`--mine` để huấn luyện 2 giai đoạn với hard-negative mining (giảm báo sai một nửa). Log-mel mỗi
phiên được cache ở `<phiên>/logmel.npy`, xác suất dò ở `<phiên>/cnn_prob.npy`.

Sau khi có `cnn_prob.npy`:

```
python research/audio/cnn_ceiling.py --all                     # tỉ lệ bắt theo khoảng cách (cần positions_*)
python research/audio/export_clips.py <phiên> --p 0.95 --n 20  # cắt WAV các lần báo sai / sót để nghe
```

Quy tắc ghi: trong lúc batch chạy, **không gõ, không click** trên máy (kể cả cửa sổ ở màn hình
khác): game mất focus là tắt tiếng, phiên đó hỏng. Batch tự kiểm tra và ghi `CẢNH BÁO` vào
`batch.log` nếu có đoạn gần im lặng; phiên hỏng thì đổi tên thành `broken_...`.
