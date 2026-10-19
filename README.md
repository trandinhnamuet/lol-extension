# LOL Spell Timer

Cửa sổ nhỏ luôn nổi trên game để bấm đếm ngược phép bổ trợ và chiêu cuối (R) của 5 địch (TOP / JGL / MID / ADC / SUP).

## Chạy
- **Bản exe (không cần cài Python):** chạy `dist/LOL Spell Timer.exe`. Có thể copy file này đi đâu cũng được; `config.json` và `cache/` sẽ được tạo ngay cạnh nó.
- **Từ mã nguồn:** nháy đúp `Chay Spell Timer.bat` (hoặc `pythonw spell_timer.py`).
- **Build lại exe:** chạy `build.bat` (cần `pip install pyinstaller pillow`).

Chi tiết kỹ thuật và giải thích về anti-cheat: xem [TECHNICAL.md](TECHNICAL.md).

> Trong LMHT: **Cài đặt → Video → Chế độ cửa sổ: Không viền (Borderless)**.
> Ở chế độ Toàn màn hình, không cửa sổ nào nổi được lên trên game.

Lần đầu chạy cần có mạng để tải ảnh tướng và ảnh phép từ Data Dragon (CDN chính thức của Riot), khoảng 3MB, lưu vào thư mục `cache/`.
Những lần sau dùng cache, và tự cập nhật khi có patch mới hoặc tướng mới.

## Cách dùng
| Thao tác | Tác dụng |
|---|---|
| Click vào **ảnh / tên tướng** | Mở bảng chọn tướng: gõ để tìm, Enter chọn tướng đầu tiên. Esc hoặc click ra ngoài để đóng |
| Click vào **⚡** (dưới tên tướng) | Xem điểm hồi phép bổ trợ từ trang bị (tự động) và cộng thêm phần từ ngọc, vd Thấu Thị Vũ Trụ +18 |
| Click trái vào **phép** | Bắt đầu đếm ngược: icon tối đi, kim quét theo chiều kim đồng hồ như trong game. Click lần nữa khi đang hồi = hủy (khi bấm nhầm) |
| Click phải vào **phép** | Đổi sang phép khác (có **TP+** = Dịch Chuyển Cường Hóa), hủy đếm ngược, hoặc bỏ ô khỏi bảng |
| Click vào **R / Q / W / E** | Đếm ngược kỹ năng của tướng đang chọn (R viền vàng, Q/W/E viền xanh); click lần nữa để hủy |
| Click phải vào **kỹ năng** | Chọn cấp kỹ năng (mỗi cấp hiện sẵn số giây), điểm hồi kỹ năng, hoặc **bỏ khỏi bảng theo dõi** |
| Click **+** ở cuối dòng | Thêm kỹ năng của tướng (vd W Yasuo, W Mel) hoặc thêm lại phép bổ trợ đã bỏ |
| Click vào **◆** (dưới tên tướng) | Xem điểm hồi kỹ năng từ trang bị (tự động) và cộng thêm phần từ ngọc / mảnh chỉ số; menu hiện luôn thời gian hồi từng kỹ năng |
| **Copy** | Copy thời điểm hồi xong theo giờ game (vd `Zed Flash 14:40`), Ctrl+V vào chat |
| Click phải vào **avatar** | Chọn tướng, chỉnh điểm hồi phép / kỹ năng (dùng khi bật chế độ gọn) |
| Kéo thanh tiêu đề | Di chuyển cửa sổ (vị trí được lưu khi tắt bằng ✕) |
| Kéo góc **◢** (dưới phải) | Phóng to / thu nhỏ cả giao diện (50% – 150%) |
| **Ctrl + lăn chuột** trên cửa sổ | Chỉnh độ trong suốt ±5% |
| **⚙** | Độ trong suốt, kích thước, **chế độ gọn** (ẩn tên tướng + điểm hồi để cửa sổ hẹp hơn) |

**Click vào app không làm mất focus game**: phím vẫn điều khiển tướng bình thường. Chỉ khi mở bảng chọn tướng (cần gõ tìm) app mới tạm lấy focus, đóng bảng là focus tự về game.

Khi vào trận (sau màn hình chờ), app tự điền tướng, phép và vị trí của địch, tự nâng cấp R theo level (6 / 11 / 16), tự đổi TP thành TP+ khi địch được nâng cấp, và **tự tính điểm hồi từ trang bị địch đang mặc** (cập nhật mỗi 2 giây khi địch mua đồ): điểm hồi kỹ năng, điểm hồi chiêu cuối (Malignance…), điểm hồi kỹ năng thường (Giáo Shojin), điểm hồi phép bổ trợ (Giày Khai Sáng). Riot không cho biết ngọc phụ của địch, nên Thấu Thị Vũ Trụ / mảnh chỉ số vẫn phải tự cộng thêm. App sẽ gợi ý khi địch có nhánh ngọc liên quan (💡).

Kỹ năng thêm/bỏ được **nhớ theo từng tướng**: thêm W cho Yasuo một lần, lần sau gặp Yasuo sẽ tự có W; bỏ R của tướng nào thì tướng đó không hiện R nữa.
Bạn vẫn có thể chọn lại bằng tay bất cứ lúc nào. Nếu không có dữ liệu từ trận, cứ chọn tay hết.

## Tùy chỉnh `config.json`
File được tạo ở lần chạy đầu.
- `cd_override`: ghi đè thời gian hồi, ví dụ `{"smite": 90, "flash": 300}`. Mặc định lấy theo Data Dragon của patch hiện tại.
- `haste_options`: các mức điểm hồi phép hiện trong menu.
- `ability_haste_options`: các mức điểm hồi kỹ năng hiện trong menu.
- `champion_abilities`: kỹ năng theo dõi của từng tướng, vd `{"Yasuo": ["W", "R"], "LeeSin": []}` (app tự ghi khi bạn thêm/bỏ).
- TP+ mặc định hồi 330s (level 1) → 240s (level 18). Các nguồn đang ghi khác nhau; muốn cố định thì thêm `"teleport_unleashed": 300` vào `cd_override`.
- `opacity`: độ trong suốt (0.2 – 1.0, mặc định 0.7). `scale`: kích thước (0.5 – 1.5, mặc định 0.8). `compact`: chế độ gọn. Cả ba chỉnh được ngay trong app.

## An toàn tài khoản
- App **không** đọc bộ nhớ game, không chèn DLL, không giả lập phím, không vẽ đè vào game. Nó chỉ là một cửa sổ Windows bình thường.
- Tướng và phép của địch lấy từ **Live Client Data API** (`127.0.0.1:2999`), API chính thức Riot mở sẵn cho ứng dụng bên thứ ba (Porofessor/Blitz cũng dùng nó). Thông tin này đều có trên bảng Tab.
- Riot chỉ cấm việc **tự động** theo dõi thời gian hồi phép của địch. Đếm ngược **bấm tay** được cho phép, và app này chỉ đếm khi bạn bấm.
