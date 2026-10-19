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
