"""Giao diện tự cập nhật: nhãn "⬆ v…" trên thanh tiêu đề khi có bản mới, hộp thoại ghi chú + tiến độ.

Kiểm tra bản mới ở luồng nền lúc mở app và mỗi CHECK_EVERY giây; chỉ luồng Tk chạm vào widget
(luồng nền ghi kết quả vào self.result / self.progress, App.after đọc ra).
"""
import os
import threading
import time
import tkinter as tk
import webbrowser

import updater

BG = "#14161a"
ROW_BG = "#1d2027"
FG = "#d8dde6"
MUTED = "#6b7380"
ACCENT = "#f0b429"
OK = "#62c370"


class UpdateController:
    def __init__(self, app, header):
        self.app = app
        self.info = None
        self.result = None  # kết quả luồng kiểm tra: ("info", UpdateInfo | None)
        self.progress = (0, 0)
        self.state = "idle"  # idle | downloading | ready | error
        self.error = None
        self.cancel_flag = False
        self.dialog = None
        self.last_check = 0
        self.checking = False
        self.label = tk.Label(header, text="", font=app.fonts["bold"], bg="#0d0f12", fg=ACCENT,
                              cursor="hand2", padx=4)
        self.label.bind("<Button-1>", lambda e: self.open_dialog())
        updater.cleanup_old()
        self.auto = os.environ.get("LOLSPELLTIMER_UPDATE_AUTO") == "1" and updater.test_overrides_allowed()
        app.root.after(2000, self.tick)
        app.root.after(30000, updater.cleanup_old)  # bản cũ vừa khởi động lại có thể còn giữ .old lúc đầu

    # ---------- kiểm tra ----------
    def start_check(self):
        if self.checking:
            return
        self.checking = True
        self.last_check = time.monotonic()

        def work():
            self.result = ("info", updater.check())
            self.checking = False

        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        try:
            if self.state != "downloading" and not self.checking and \
                    time.monotonic() - self.last_check >= (updater.CHECK_EVERY if self.last_check else 0):
                self.start_check()
            if self.result is not None:
                _, info = self.result
                self.result = None
                if info is not None and info.state == "available":
                    self.info = info
                    self.show_label()
                    if self.auto and self.state == "idle":
                        self.begin_download()
                elif info is not None:
                    self.info = None
                    self.label.pack_forget()
            if self.state == "ready":
                self.finish_install()
            self.refresh_dialog()
        except Exception as e:  # không để lỗi cập nhật làm đơ app
            self.state, self.error = "error", str(e)
        self.app.root.after(300 if self.state == "downloading" else 1000, self.tick)

    def show_label(self):
        compact = self.app.cfg.get("compact")
        self.label.config(text="⬆" if compact else f"⬆ v{self.info.latest}")
        if not self.label.winfo_ismapped():
            self.label.pack(side="left", padx=2)

    # ---------- hộp thoại ----------
    def open_dialog(self):
        if self.dialog is not None:
            try:
                self.dialog.lift()
                return
            except tk.TclError:
                self.dialog = None
        if self.info is None:
            return
        root = self.app.root
        d = tk.Toplevel(root)
        d.title("Cập nhật LOL Spell Timer")
        d.configure(bg=BG)
        d.attributes("-topmost", True)
        d.resizable(False, False)
        d.geometry(f"+{root.winfo_x() + 20}+{root.winfo_y() + 40}")
        f = self.app.fonts
        self.title_label = tk.Label(d, font=f["name"], bg=BG, fg=FG, justify="left")
        self.title_label.pack(anchor="w", padx=12, pady=(10, 4))
        self.notes = tk.Text(d, width=46, height=8, bg=ROW_BG, fg=FG, bd=0, wrap="word",
                             font=f["text"], padx=6, pady=4)
        self.notes.insert("1.0", self.info.notes_since())
        self.notes.config(state="disabled")
        self.notes.pack(padx=12)
        self.warn = tk.Label(d, font=f["text"], bg=BG, fg=ACCENT, wraplength=330, justify="left")
        self.warn.pack(anchor="w", padx=12, pady=(6, 0))
        self.bar = tk.Canvas(d, width=330, height=8, bg=ROW_BG, highlightthickness=0)
        self.bar.pack(padx=12, pady=(6, 0))
        self.bar_fill = self.bar.create_rectangle(0, 0, 0, 8, fill=OK, width=0)
        self.status_label = tk.Label(d, font=f["text"], bg=BG, fg=MUTED, wraplength=330, justify="left")
        self.status_label.pack(anchor="w", padx=12, pady=(2, 0))
        row = tk.Frame(d, bg=BG)
        row.pack(fill="x", padx=12, pady=10)
        self.go = tk.Button(row, text="Cập nhật", command=self.begin_download, bg=ACCENT, fg="#000000",
                            bd=0, padx=14, pady=3, cursor="hand2", font=f["bold"])
        self.go.pack(side="left")
        self.later = tk.Button(row, text="Để sau", command=self.close_dialog, bg=ROW_BG, fg=FG, bd=0,
                               padx=10, pady=3, cursor="hand2", font=f["text"])
        self.later.pack(side="left", padx=6)
        page = tk.Label(row, text="Xem trên GitHub", font=f["text"], bg=BG, fg=MUTED, cursor="hand2")
        page.pack(side="right")
        page.bind("<Button-1>", lambda e: webbrowser.open(updater.safe_page(self.info.page)))
        d.protocol("WM_DELETE_WINDOW", self.close_dialog)
        self.dialog = d
        self.refresh_dialog()

    def close_dialog(self):
        if self.state == "downloading":
            self.cancel_flag = True
        if self.dialog is not None:
            try:
                self.dialog.destroy()
            except tk.TclError:
                pass
            self.dialog = None

    def refresh_dialog(self):
        d = self.dialog
        if d is None or self.info is None:
            return
        try:
            self.title_label.config(text=f"Có bản mới v{self.info.latest}  (đang dùng v{self.info.current})")
            in_game = self.app.game_time is not None
            self.warn.config(text="Đang trong trận: app sẽ khởi động lại và các đếm ngược đang chạy sẽ mất."
                             if in_game else "")
            done, total = self.progress
            self.bar.coords(self.bar_fill, 0, 0, 330 * (done / total if total else 0), 8)
            if not updater.is_frozen():
                self.go.config(state="disabled")
                self.status_label.config(text="Đang chạy từ mã nguồn: tải bản mới ở GitHub.", fg=MUTED)
            elif self.state == "downloading":
                self.go.config(state="disabled", text="Đang tải…")
                self.status_label.config(text=f"{done / 1e6:.1f} / {total / 1e6:.1f} MB", fg=MUTED)
            elif self.state == "error":
                self.go.config(state="normal", text="Thử lại")
                self.status_label.config(text=f"Lỗi: {self.error}", fg="#e06c6c")
            else:
                self.go.config(state="normal", text="Cập nhật")
                self.status_label.config(text="", fg=MUTED)
        except tk.TclError:
            self.dialog = None

    # ---------- tải và cài ----------
    def begin_download(self):
        if self.info is None or self.state == "downloading" or not updater.is_frozen() and not self.auto:
            return
        if self.dialog is None and not self.auto:
            self.open_dialog()
        self.state, self.error, self.cancel_flag = "downloading", None, False
        self.progress = (0, int(self.info.asset.get("size") or 0))
        info = self.info

        def work():
            try:
                self.new_path = updater.download(info, progress=lambda k, t: setattr(self, "progress", (k, t)),
                                                 cancel=lambda: self.cancel_flag)
                self.state = "ready"
            except Exception as e:  # noqa: BLE001
                self.state = "idle" if self.cancel_flag else "error"
                self.error = str(e)

        threading.Thread(target=work, daemon=True).start()

    def finish_install(self):
        self.state = "installing"
        try:
            updater.install(self.new_path, self.info.asset["sha256"])
        except Exception as e:  # noqa: BLE001
            self.state, self.error = "error", str(e)
            return
        updater.restart()
        self.app.quit()
