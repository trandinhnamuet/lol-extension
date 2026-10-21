"""Kiểm tra updater.py không cần mạng thật: máy chủ HTTP cục bộ + thư mục tạm.
Chạy: python -m unittest tests.test_updater -v   (từ thư mục gốc project)"""
import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import updater  # noqa: E402


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class UpdaterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.payload = os.urandom(300_000)
        open(os.path.join(cls.dir, "new.exe"), "wb").write(cls.payload)
        cls.sha = hashlib.sha256(cls.payload).hexdigest()
        h = lambda *a, **k: Handler(*a, directory=cls.dir, **k)  # noqa: E731
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def manifest(self, version="9.9.9", sha=None, size=None, name="new.exe"):
        m = {"version": version, "asset": {"url": f"http://127.0.0.1:{self.port}/{name}",
             "sha256": sha or self.sha, "size": size or len(self.payload)}, "notes": {version: "- **x**"}}
        json.dump(m, open(os.path.join(self.dir, "version.json"), "w"))
        return f"http://127.0.0.1:{self.port}/version.json"

    def test_versions(self):
        self.assertLess(updater.vtuple("1.2.0"), updater.vtuple("1.10.0"))
        self.assertLess(updater.vtuple("v1.2"), updater.vtuple("1.2.1"))
        self.assertEqual(updater.vtuple("abc"), (0,))

    def test_available_and_current(self):
        url = self.manifest("1.3.0")
        self.assertEqual(updater.check("1.2.0", url).state, "available")
        self.assertEqual(updater.check("1.3.0", url).state, "current")
        self.assertEqual(updater.check("1.4.0", url).state, "current")

    def test_offline_returns_none(self):
        self.assertIsNone(updater.check("1.0.0", "http://127.0.0.1:1/version.json"))

    def test_bad_manifest_rejected(self):
        open(os.path.join(self.dir, "bad.json"), "w").write('{"version": "2"}')
        self.assertIsNone(updater.check("1.0.0", f"http://127.0.0.1:{self.port}/bad.json"))

    def test_download_install_ok(self):
        info = updater.check("1.0.0", self.manifest())
        d = tempfile.mkdtemp()
        exe = os.path.join(d, "app.exe")
        open(exe, "wb").write(b"old")
        new = updater.download(info, dst=exe + ".new")
        updater.install(new, info.asset["sha256"], exe=exe)
        self.assertEqual(open(exe, "rb").read(), self.payload)
        self.assertEqual(open(exe + ".old", "rb").read(), b"old")
        self.assertEqual(updater.cleanup_old(exe), 1)
        self.assertFalse(os.path.exists(exe + ".old"))

    def test_wrong_sha_rejected_and_no_leftovers(self):
        info = updater.check("1.0.0", self.manifest(sha="0" * 64))
        d = tempfile.mkdtemp()
        with self.assertRaises(updater.UpdateError):
            updater.download(info, dst=os.path.join(d, "app.exe.new"))
        self.assertEqual(os.listdir(d), [])

    def test_truncated_rejected(self):
        info = updater.check("1.0.0", self.manifest(size=len(self.payload) + 5))
        with self.assertRaises(updater.UpdateError):
            updater.download(info, dst=os.path.join(tempfile.mkdtemp(), "app.exe.new"))

    def test_untrusted_url_blocked_when_frozen_without_flag(self):
        info = updater.check("1.0.0", self.manifest())
        old = getattr(sys, "frozen", None)
        sys.frozen = True
        try:
            with self.assertRaises(updater.UpdateError):
                updater.download(info, dst=os.path.join(tempfile.mkdtemp(), "app.exe.new"))
            self.assertFalse(updater.test_overrides_allowed())
        finally:
            if old is None:
                del sys.frozen
            else:
                sys.frozen = old

    def test_tampered_new_file_not_installed(self):
        d = tempfile.mkdtemp()
        exe = os.path.join(d, "app.exe")
        open(exe, "wb").write(b"old")
        open(exe + ".new", "wb").write(b"evil")
        with self.assertRaises(updater.UpdateError):
            updater.install(exe + ".new", self.sha, exe=exe)
        self.assertEqual(open(exe, "rb").read(), b"old")

    def test_safe_page(self):
        self.assertEqual(updater.safe_page("C:/evil.exe"), updater.RELEASES_PAGE)
        self.assertEqual(updater.safe_page("https://github.com/x/y"), "https://github.com/x/y")


if __name__ == "__main__":
    unittest.main()
