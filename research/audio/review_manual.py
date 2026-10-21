"""Đối chiếu những lần NGƯỜI DÙNG BẤM TAY với những gì app đã nghe được: mỗi lần bấm tay một phép là một "nhãn" rằng người dùng
thấy/biết địch vừa dùng phép đó, nên nếu app không tự bấm trước đó thì đó là một lần bỏ lỡ cần giải thích.

    python research/audio/review_manual.py <data>              # thư mục data của app (có auto_flash.log, debug_frames/)
    python research/audio/review_manual.py <data> --window 12  # nhìn lại bao nhiêu giây trước lúc bấm

Đọc auto_flash.log: dòng "TAY bấm <tướng> <phép>" (mono = giờ lúc bấm) và các dòng "tiếng ..." trước đó; đọc
debug_frames/probs_*.csv (mono, xác suất từng phép, rms_db mỗi 100 ms, cùng đồng hồ monotonic) để biết lúc đó mô hình
thấy gì. Phân loại mỗi lần bấm tay:
  - TỰ BẤM TRƯỚC: app đã tự bấm đúng ô đó ngay trước (người dùng bấm lại / sửa): không phải bỏ lỡ.
  - NGHE NHƯNG HỎI: app nghe thấy tiếng nhưng chỉ hỏi (quy kết không chắc), người dùng tự bấm.
  - NGHE NHƯNG BỎ QUA: app nghe thấy nhưng loại (không trong tầm, ...).
  - KHÔNG NGHE: không có tiếng vượt ngưỡng; in xác suất cao nhất và âm lượng trong cửa sổ để biết là mô hình trượt
    (xác suất 0,3–0,9, có âm thanh) hay thật sự không có âm thanh (rms rất thấp).
Ảnh minimap 10 s trước lúc bấm nằm ở debug_frames/NNN_tay_<phép>_<tướng>_g<giây>/.
"""
import argparse
import csv
import glob
import os
import re

import numpy as np

LINE = re.compile(r"\S+ mono=([\d.]+) game=(\S+) (.*)")


def parse_log(path):
    out = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = LINE.match(line.rstrip("\n"))
        if m:
            out.append((float(m.group(1)), m.group(2), m.group(3)))
    return out


def load_probs(folder):
    rows = []
    for p in sorted(glob.glob(os.path.join(folder, "probs_*.csv"))):
        with open(p, encoding="utf-8") as f:
            r = csv.reader(f)
            head = next(r, None)
            if not head or head[0] != "mono":
                continue
            has_rms = head[-1] == "rms_db"
            names = [h for h in head[1:] if h != "rms_db"]
            for row in r:
                try:
                    rows.append([float(x) for x in row])
                except ValueError:
                    pass
    return (names if rows else []), np.array(rows) if rows else np.zeros((0, 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data")
    ap.add_argument("--window", type=float, default=12.0)
    args = ap.parse_args()
    log = parse_log(os.path.join(args.data, "auto_flash.log"))
    names, probs = load_probs(os.path.join(args.data, "debug_frames"))
    presses = [(m, g, t) for m, g, t in log if t.startswith("TAY bấm")]
    sounds = [(m, g, t) for m, g, t in log if t.startswith("tiếng")]
    print(f"{len(presses)} lần bấm tay, {len(sounds)} tiếng app nghe thấy"
          f"{'; có nhật ký xác suất' if len(probs) else '; KHÔNG có probs_*.csv (chạy bản < 1.4.2 hoặc chưa bật chẩn đoán)'}\n")
    tally = {}
    for m, g, t in presses:
        parts = t.split(" ")
        champ, spell = parts[2], parts[3] if len(parts) > 3 else "?"
        key = "ignite" if spell.lower().startswith("ignite") else "flash"
        before = [(sm, sg, st) for sm, sg, st in sounds if m - args.window <= sm <= m + 0.5 and (key in st or (key == "flash" and not re.match(r"tiếng (ignite)", st)))]
        auto = [x for x in before if "TỰ BẤM" in x[2] and champ in x[2]]
        if auto:
            verdict = "TỰ BẤM TRƯỚC"
        elif any("HỎI" in x[2] for x in before):
            verdict = "NGHE NHƯNG HỎI"
        elif before:
            verdict = "NGHE NHƯNG BỎ QUA"
        else:
            verdict = "KHÔNG NGHE"
        extra = ""
        if verdict == "KHÔNG NGHE" and len(probs):
            sel = (probs[:, 0] >= m - args.window) & (probs[:, 0] <= m)
            if sel.any():
                col = 1 + (names.index(key) if key in names else 0)
                p = probs[sel, col]
                rms = probs[sel, 1 + len(names)] if probs.shape[1] > len(names) + 1 else None
                extra = f"  xác suất {key} cao nhất {p.max():.2f}" + (f", âm lượng trung vị {np.median(rms):.0f} dB (tối thiểu {rms.min():.0f})" if rms is not None else "")
            else:
                extra = "  (không có mẫu xác suất trong cửa sổ)"
        tally[verdict] = tally.get(verdict, 0) + 1
        print(f"game {g:>6}  bấm tay {champ:12s} {spell:7s} -> {verdict}{extra}")
        for sm, sg, st in before:
            print(f"        {m - sm:5.1f} s trước: tiếng lúc {sg}: {st[:100]}")
    print("\nTổng kết:", ", ".join(f"{k} {v}" for k, v in sorted(tally.items())) or "không có lần bấm tay nào")


if __name__ == "__main__":
    main()
