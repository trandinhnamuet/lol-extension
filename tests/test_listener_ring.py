"""Bộ đệm vòng của flash_listener phải chịu được khoảng im lặng dài (loopback không gửi dữ liệu khi hệ thống im lặng).
Chạy: python -m unittest tests.test_listener_ring -v   (từ thư mục gốc project)"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flash_listener as fl  # noqa: E402


def make():
    lst = fl.FlashListener(lambda *a: None, models={})
    lst.t0 = 0.0
    return lst


class RingTest(unittest.TestCase):
    def test_write_normal(self):
        lst = make()
        lst._write(np.arange(1000, dtype=np.float32))
        y, _ = lst._last(500)
        self.assertEqual(float(y[-1]), 999.0)
        self.assertEqual(lst.written, 1000)

    def test_write_larger_than_buffer(self):
        lst = make()
        size = len(lst.buf)
        big = np.arange(size * 3, dtype=np.float32)
        lst._write(big)  # trước khi sửa: ValueError broadcast
        self.assertEqual(lst.written, size * 3)
        y, _ = lst._last(1000)
        self.assertEqual(float(y[-1]), float(size * 3 - 1))

    def test_wrap_around_continuity(self):
        lst = make()
        size = len(lst.buf)
        lst._write(np.arange(size - 10, dtype=np.float32))
        lst._write(np.arange(size - 10, size + 90, dtype=np.float32))
        y, _ = lst._last(100)
        self.assertTrue(np.array_equal(y, np.arange(size - 10, size + 90, dtype=np.float32)))

    def test_long_silence_then_audio(self):
        """Mô phỏng _callback sau 3 giờ không có dữ liệu."""
        import time
        lst = make()
        lst.channels, lst.rate = 1, fl.SR
        lst.t0 = time.monotonic() - 3 * 3600
        data = (np.ones(1024, np.int16) * 1000).tobytes()
        import types
        sys.modules.setdefault("pyaudiowpatch", types.SimpleNamespace(paContinue=0))
        lst._callback(data, 1024, None, None)
        self.assertNotIn("lỗi", lst.status)
        y, _ = lst._last(1024)
        self.assertAlmostEqual(float(y[-1]), 1000 / 32768, places=4)
        lst._callback(data, 1024, None, None)  # lần sau vẫn chạy bình thường
        self.assertNotIn("lỗi", lst.status)


if __name__ == "__main__":
    unittest.main()
