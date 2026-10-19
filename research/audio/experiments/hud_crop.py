"""Cắt và phóng to vùng HUD (ô kỹ năng + phép bổ trợ) của vài khung hình để lấy tọa độ."""
import os
import sys

import cv2
import numpy as np

frames_dir, out = sys.argv[1], sys.argv[2]
names = sys.argv[3:]
tiles = []
for name in names:
    img = cv2.imread(os.path.join(frames_dir, f"{name}.jpg"))
    crop = img[465:540, 360:560]
    big = cv2.resize(crop, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
    # lưới 10px gốc để đọc tọa độ
    for x in range(0, big.shape[1], 50):
        cv2.line(big, (x, 0), (x, big.shape[0]), (0, 255, 255), 1)
        cv2.putText(big, str(360 + x // 5), (x + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
    for y in range(0, big.shape[0], 50):
        cv2.line(big, (0, y), (big.shape[1], y), (0, 255, 255), 1)
        cv2.putText(big, str(465 + y // 5), (2, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
    cv2.putText(big, name, (big.shape[1] - 90, big.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    tiles.append(big)
cv2.imwrite(out, np.vstack(tiles))
print("saved", out)
