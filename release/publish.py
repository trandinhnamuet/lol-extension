"""Đăng một bản phát hành lên repo công khai để app tự cập nhật.

    python release/publish.py                 # đăng bản APP_VERSION trong version.py (cần dist/LOL Spell Timer.exe)
    python release/publish.py --dry-run       # chỉ dựng version.json trong release/out/, không đăng
    python release/publish.py --repo owner/name

Các bước: đọc version.py, ghi lại tools/version_info.txt, tính SHA-256 của exe, gom release/notes/v*.md thành
version.json ({"version", "page", "asset": {name,url,size,sha256}, "notes": {"1.2.0": "..."}}), tạo release
v<version> ở repo phát hành rồi tải lên: LOL.Spell.Timer.exe, LOL.Spell.Timer.exe.sha256, version.json.
App đọc https://github.com/<repo>/releases/latest/download/version.json nên bản đăng sau cùng là bản "mới nhất".
Token lấy từ Git Credential Manager (github.com).
"""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from updater import REPO as DEFAULT_REPO  # noqa: E402
from version import APP_VERSION  # noqa: E402

EXE = os.path.join(ROOT, "dist", "LOL Spell Timer.exe")
ASSET = "LOL-Spell-Timer-update.exe"  # exe lẻ cho bộ tự cập nhật (GitHub đổi dấu cách thành dấu chấm trong tên tệp)
ZIP = "LOL-Spell-Timer.zip"  # gói người dùng tải: thư mục "LOL Spell Timer" chứa "LOL Spell Timer.exe"
ZIP_DIR = "LOL Spell Timer"
EXE_NAME = "LOL Spell Timer.exe"
OUT = os.path.join(ROOT, "release", "out")


def token():
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise SystemExit("không lấy được token GitHub từ Git Credential Manager")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sync_version_info(version):
    p = os.path.join(ROOT, "tools", "version_info.txt")
    s = open(p, encoding="utf-8").read()
    nums = (version.split(".") + ["0", "0", "0"])[:4]
    s = re.sub(r"filevers=\([^)]*\), prodvers=\([^)]*\)",
               f"filevers=({', '.join(nums)}), prodvers=({', '.join(nums)})", s)
    s = re.sub(r"('FileVersion', ')[^']*", rf"\g<1>{version}", s)
    s = re.sub(r"('ProductVersion', ')[^']*", rf"\g<1>{version}", s)
    open(p, "w", encoding="utf-8").write(s)


def notes():
    out = {}
    for p in glob.glob(os.path.join(ROOT, "release", "notes", "v*.md")):
        out[os.path.basename(p)[1:-3]] = open(p, encoding="utf-8").read().strip()
    return out


def make_zip(exe, version):
    """LOL-Spell-Timer.zip: thư mục "LOL Spell Timer" có exe đúng tên và một tệp hướng dẫn ngắn."""
    import zipfile
    path = os.path.join(OUT, ZIP)
    guide = ("LOL Spell Timer " + version + "\r\n\r\n"
             "1. Giải nén thư mục này ở đâu cũng được, mở LOL Spell Timer.exe.\r\n"
             "2. Trong LMHT: Cài đặt > Video > Chế độ cửa sổ: Không viền (Borderless).\r\n"
             "3. Lần đầu cần mạng để tải ảnh tướng và phép. Cấu hình, ảnh tải về và nhật ký nằm trong thư mục data cạnh exe.\r\n"
             "4. App tự báo khi có bản mới (nhãn ⬆ trên thanh tiêu đề), bấm Cập nhật là xong.\r\n")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(exe, f"{ZIP_DIR}/{EXE_NAME}")
        z.writestr(f"{ZIP_DIR}/Doc toi.txt", guide.encode("utf-8"))
    return path


def api(method, url, tok, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"token {tok}", "Accept": "application/vnd.github+json", "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read() or b"{}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--exe", default=EXE)
    args = ap.parse_args()
    version, tag = APP_VERSION, f"v{APP_VERSION}"
    if not os.path.exists(args.exe):
        raise SystemExit(f"chưa có {args.exe}: chạy build.bat trước")
    sync_version_info(version)
    digest, size = sha256(args.exe), os.path.getsize(args.exe)
    all_notes = notes()
    if version not in all_notes:
        raise SystemExit(f"thiếu release/notes/v{version}.md (ghi chú của bản này)")
    manifest = {"version": version, "page": f"https://github.com/{args.repo}/releases/tag/{tag}",
                "asset": {"name": ASSET, "size": size, "sha256": digest,
                          "url": f"https://github.com/{args.repo}/releases/download/{tag}/{ASSET}"},
                "notes": all_notes}
    os.makedirs(OUT, exist_ok=True)
    mpath = os.path.join(OUT, "version.json")
    json.dump(manifest, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    spath = os.path.join(OUT, ASSET + ".sha256")
    open(spath, "w").write(f"{digest}  {ASSET}\n")
    zpath = make_zip(args.exe, version)
    print(f"{tag}: {size / 1e6:.1f} MB, sha256 {digest[:16]}…  -> {mpath}; zip {os.path.getsize(zpath) / 1e6:.1f} MB")
    if args.dry_run:
        return
    tok = token()
    body = (f"{all_notes[version]}\n\n## Tải về\n\n- Tải **{ZIP}**, giải nén, mở `{EXE_NAME}`. Không cần cài Python.\n"
            f"- Đang dùng từ v1.2.0 trở lên: app tự báo có bản mới, bấm **Cập nhật** là xong (`{ASSET}` và `version.json` "
            "chỉ dành cho bộ tự cập nhật, không cần tải)." + "\n- Trong LMHT: Cài đặt → Video → Chế độ cửa sổ: Không viền (Borderless)." + "\n")
    rel = api("POST", f"https://api.github.com/repos/{args.repo}/releases", tok,
              {"tag_name": tag, "name": f"LOL Spell Timer {tag}", "body": body, "draft": False, "prerelease": False,
               "make_latest": "true"})
    up = rel["upload_url"].split("{")[0]
    for path, name, ctype in ((zpath, ZIP, "application/zip"), (args.exe, ASSET, "application/octet-stream"),
                              (spath, ASSET + ".sha256", "text/plain"),
                              (mpath, "version.json", "application/json")):
        a = api("POST", f"{up}?name={name}", tok, raw=open(path, "rb").read(), ctype=ctype)
        print("đã tải lên:", a["browser_download_url"], a["size"], "byte")
    print("Release:", rel["html_url"])


if __name__ == "__main__":
    main()
