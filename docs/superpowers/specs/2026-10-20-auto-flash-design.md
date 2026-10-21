# Tự bắt Flash: nghe tiếng, quy kết bằng minimap, bấm timer

Ngày 20/10/2026. Đã duyệt.

## Mục tiêu
Khi một địch dùng Flash, app tự bấm đếm ngược Flash của đúng người đó mà người dùng không phải
nhìn hay click. Không đọc bộ nhớ game, không chèn DLL, chỉ nghe âm thanh hệ thống và chụp vùng
minimap trên màn hình.

## Thành phần
- `flash_listener.py`: thu loopback WASAPI (pyaudiowpatch), log-mel trượt (cùng tham số với
  `research/audio/common.py`), mô hình ONNX `models/flash_cnn.onnx` (xuất từ
  `research/audio/models/flash_cnn.pt`) chạy onnxruntime. Mỗi 100 ms chấm cửa sổ 1 s cuối; đỉnh
  xác suất ≥ ngưỡng (mặc định 0,95), cách nhau ≥ 1 s → sự kiện `(t_monotonic, p)`.
  Chuẩn hóa từng băng theo trung vị / IQR chạy trên 120 s gần nhất.
- `minimap_tracker.py`: mss chụp vùng minimap ~20 fps; tìm icon địch bằng vòng viền đỏ (mặt nạ màu
  + HoughCircles, loại trụ/ping vì lõi đặc đỏ); trong mỗi vòng so chân dung Data Dragon của 5 địch
  (NCC mặt nạ tròn) để biết ai, có nhớ vết; lịch sử vị trí 3 s mỗi địch.
  `who_jumped(t)` → các địch có bước nhảy ≥ 5 px trong ≤ 0,25 s nằm trong [t−0,7 s, t+0,4 s].
  (Đổi so với bản duyệt ban đầu: khớp chân dung trên cả minimap vừa chậm 60 ms/tướng vừa khớp
  nhầm nền; tìm vòng đỏ trước thì 13 ms/khung và 4/4 đúng trong thử nghiệm.)
- `spell_timer.py`: tùy chọn ⚙ "Tự bắt Flash". Sự kiện âm thanh + đúng một địch nhảy → gọi
  `TimerSlot.start()` của ô Flash hàng đó, ghi nhãn "tự động" 3 s. Không có hoặc nhiều ứng viên →
  dải chân dung (ứng viên, hoặc cả 5 nếu minimap không chạy) hiện 8 s, click để gán.
  Minimap không bắt được (sai vùng, không tìm thấy icon) → luôn hỏi.

## Dòng dữ liệu
Loopback → ring buffer → log-mel+delta → ONNX → đỉnh → hàng đợi sự kiện → `App.tick()` (luồng Tk)
→ `tracker.who_jumped(t)` → start timer / hiện dải.

## Xử lý lỗi
- Không có thiết bị loopback / onnxruntime lỗi: tắt tính năng, ghi trạng thái "không nghe được".
- Minimap không ra icon nào trong 10 s khi đang trong trận: chuyển sang chế độ hỏi, báo trong ⚙.
- Game mất focus (tắt tiếng): không có sự kiện, không làm gì.
- Mọi lỗi trong luồng nền được bắt, không làm đơ UI.

## Kiểm thử
1. Offline: `research/audio/test_listener_offline.py` đưa `audio.wav` của phiên replay qua đúng
   đường streaming, so với `flash_events.csv`: phải tương đương kết quả offline (±5%).
2. Offline minimap: khớp icon trên ảnh 960×540 của phiên `replay_1609077581`, xuất ảnh kiểm.
3. Live: chạy app trong lúc xem replay (camera gắn vào người chơi), ghi `auto_flash.log`, đối chiếu
   HUD. Đạt khi gán đúng ≥ 90% Flash địch thấy trên minimap, gán sai ≤ 1 lần/trận.

## Đóng gói
Thêm onnxruntime, pyaudiowpatch, mss, numpy, scipy, opencv-python-headless vào build.
