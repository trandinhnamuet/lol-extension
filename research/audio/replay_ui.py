"""Điều khiển giao diện replay bằng chuột (1080p mặc định; scale theo chiều cao màn hình): ô "Sương Mù" ở góc dưới trái.

    python research/audio/replay_ui.py Xanh        # Xanh | Đỏ | Tất cả

Replay API chỉ có công tắc fogOfWar, không chọn được phe; phím V gửi giả không có tác dụng. Chọn "Xanh" (phe ORDER) làm vùng
nhìn thấy trên minimap tối đi giống trận thật, nhưng icon tướng địch VẪN hiện: dùng minimap_tracker.fog_min_lum để bỏ các icon
nằm trong vùng tối (xem RESEARCH.md mục 9.9).
"""
import ctypes
import sys
import time

DROP = (221, 1011)  # ô chọn phe, toạ độ ở 1080p
OPTIONS = {"Xanh": (187, 951), "Đỏ": (181, 974), "Tất cả": (189, 998)}


def set_fog(name):
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    hwnd = user32.FindWindowW(None, "League of Legends (TM) Client")
    if not hwnd:
        raise RuntimeError("không thấy cửa sổ game")
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    k = user32.GetSystemMetrics(1) / 1080

    def click(p):
        user32.SetCursorPos(int(p[0] * k), int(p[1] * k))
        time.sleep(0.2)
        user32.mouse_event(2, 0, 0, 0, 0)
        time.sleep(0.06)
        user32.mouse_event(4, 0, 0, 0, 0)
        time.sleep(0.6)

    click(DROP)
    click(OPTIONS[name])
    user32.SetCursorPos(int(960 * k), int(300 * k))  # đưa chuột ra khỏi HUD
    return True


if __name__ == "__main__":
    set_fog(sys.argv[1] if len(sys.argv) > 1 else "Xanh")
    print("đã chọn sương mù", sys.argv[1] if len(sys.argv) > 1 else "Xanh")
