# LOL Spell Timer

Cửa sổ nhỏ luôn nổi trên game để bấm đếm ngược phép bổ trợ và chiêu cuối (R) của 5 địch (TOP / JGL / MID / ADC / SUP).

## Chạy
- **Bản exe (không cần cài Python):** tải `LOL.Spell.Timer.exe` ở [trang phát hành](https://github.com/trandinhnamuet/lol-spell-timer-releases/releases/latest) (repo công khai riêng, không chứa mã nguồn). Có thể để file này ở đâu cũng được; `config.json` và `cache/` sẽ được tạo ngay cạnh nó.
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

## Tự cập nhật
Từ v1.2.0, mở app là tự kiểm tra bản mới (và 6 giờ một lần khi mở lâu). Có bản mới thì nhãn **⬆ v…** hiện trên thanh tiêu đề: bấm vào, đọc ghi chú, bấm **Cập nhật**. App tải exe mới, kiểm SHA-256, đổi tên file đang chạy, thay bằng bản mới rồi tự khởi động lại; `config.json` và `cache/` giữ nguyên. Không có mạng thì dùng bình thường. Đang trong trận thì hộp thoại cảnh báo các đếm ngược đang chạy sẽ mất. **⚙ → Kiểm tra cập nhật** để kiểm tra thủ công. Chạy từ mã nguồn chỉ báo, không tự thay file.

Phát hành bản mới (người bảo trì): sửa `version.py`, viết `release/notes/v<số>.md`, chạy `build.bat`, rồi `python release/publish.py` (có `--dry-run`). Script tính SHA-256, tạo `version.json` gom ghi chú các bản và đăng release lên repo phát hành.

## Tự bắt Flash (nghe tiếng + minimap)

Bật trong **⚙ → Tự bắt Flash**. App nghe âm thanh hệ thống (loopback, không cần micro) bằng một
mô hình nhỏ nhận ra tiếng Tốc Biến, đồng thời chụp vùng minimap ~20 lần/giây để xem icon địch nào
vừa nhảy. Nghe thấy Flash và đúng một địch nhảy → tự bấm đếm ngược Flash của người đó (ô hiện
nhãn **auto** 3 giây, click lần nữa nếu sai). Không rõ ai → hiện dải chân dung ngay dưới bảng,
click một cái để gán, 6 giây không click thì tự ẩn.

- Game phải **có focus** (tiếng game tắt khi mất focus) và ở chế độ Không viền.
- Tắt nhạc trong game giúp nghe tốt hơn (Cài đặt → Âm thanh → Nhạc = 0).
- Mặc định vùng minimap là góc dưới phải màn hình 1920×1080 với tỉ lệ minimap mặc định. Màn hình
  hoặc tỉ lệ khác: **⚙ → Chụp thử vùng minimap** rồi xem `minimap_snapshot.png` (icon tìm được
  khoanh xanh), chỉnh `minimap_rect: [x, y, w, h]` trong `config.json`.
- Tốn ~3% một lõi CPU, ~80 MB RAM, không cần GPU. Mọi quyết định ghi vào `auto_flash.log`.
- Đo trên replay (xem `research/audio/RESEARCH.md` mục 9): mô hình âm thanh nghe thấy ~70–80%
  Flash với ~1 báo sai mỗi 10 phút ở ngưỡng 0,95 (`auto_flash_threshold`). Trong số nghe thấy, tự
  bấm được đúng người khi địch đang hiện trên minimap lúc Flash (khoảng 30–60% tùy trận), còn lại
  hỏi bằng dải chân dung; các bài thử không ghi nhận lần tự bấm sai người. Tiếng Flash trong giao
  tranh đông dễ bị lấn, nên không phải lần nào cũng nghe thấy; dải hỏi cũng hiện khi đồng minh
  Flash (tiếng giống nhau), cứ bỏ qua.

### Thiêu Đốt (từ v1.3.0)
Cùng bộ nghe (mô hình thứ hai trên cùng log-mel, thêm ~2,5% một lõi). Thiêu Đốt nhắm mục tiêu nên không có cú nhảy; thay vào đó: kẻ thi triển phải là địch mang Thiêu Đốt đang cách một đồng minh (hoặc bạn) không quá tầm 600 trên minimap lúc nghe thấy tiếng. Một ứng viên → tự bấm. Hỏi khi: nhiều ứng viên, không ứng viên nào trong tầm, hoặc một đồng minh cũng mang Thiêu Đốt đứng trong tầm (tiếng của hai phe giống nhau, không phân biệt được ai vừa dùng). Tắt riêng bằng `auto_ignite: false`.

## Tùy chỉnh `config.json`
File được tạo ở lần chạy đầu.
- `cd_override`: ghi đè thời gian hồi, ví dụ `{"smite": 90, "flash": 300}`. Mặc định lấy theo Data Dragon của patch hiện tại.
- `haste_options`: các mức điểm hồi phép hiện trong menu.
- `ability_haste_options`: các mức điểm hồi kỹ năng hiện trong menu.
- `champion_abilities`: kỹ năng theo dõi của từng tướng, vd `{"Yasuo": ["W", "R"], "LeeSin": []}` (app tự ghi khi bạn thêm/bỏ).
- TP+ mặc định hồi 330s (level 1) → 240s (level 18). Các nguồn đang ghi khác nhau; muốn cố định thì thêm `"teleport_unleashed": 300` vào `cd_override`.
- `auto_flash`: bật tự bắt Flash. `auto_ignite` (mặc định true) và `auto_ignite_threshold`: phần Thiêu Đốt. `auto_flash_threshold`: ngưỡng xác suất (0,9 nhạy hơn, 0,98 ít báo sai hơn). `auto_flash_ask_unknown`: hỏi khi không biết ai (false = chỉ tự bấm khi chắc). `minimap_rect`: vùng minimap.
- `auto_flash_debug_frames` (mặc định false): ghi chẩn đoán vào `data/debug_frames/` để tìm lý do app bỏ lỡ: ảnh minimap quanh mỗi tiếng nghe được, âm thanh thô `audio_*.pcm` (int16 mono 48 kHz), `probs_*.csv` (xác suất + âm lượng mỗi 100 ms) và, mỗi lần **bạn bấm tay** một ô, 10 giây ảnh minimap trước đó (thư mục `NNN_tay_...`). Mỗi lần bấm/hủy tay cũng ghi vào `auto_flash.log` (`TAY bấm <tướng> <phép>`). Sau trận chạy `python research/audio/review_manual.py data` để xem từng lần bấm tay có phải là lần app bỏ lỡ không, và vì sao.
- `opacity`: độ trong suốt (0.2 – 1.0, mặc định 0.7). `scale`: kích thước (0.5 – 1.5, mặc định 0.8). `compact`: chế độ gọn. Cả ba chỉnh được ngay trong app.

## An toàn tài khoản
- App **không** đọc bộ nhớ game, không chèn DLL, không giả lập phím, không vẽ đè vào game. Nó chỉ là một cửa sổ Windows bình thường.
- Tướng và phép của địch lấy từ **Live Client Data API** (`127.0.0.1:2999`), API chính thức Riot mở sẵn cho ứng dụng bên thứ ba (Porofessor/Blitz cũng dùng nó). Thông tin này đều có trên bảng Tab.
- Riot chỉ cấm việc **tự động** theo dõi thời gian hồi phép của địch. Đếm ngược **bấm tay** được cho phép, và app này chỉ đếm khi bạn bấm.
