"""Vẽ icon cho LOL Spell Timer bằng Pillow -> assets/icon.ico (+ icon.png để xem trước).

Vẽ ở 1024px rồi thu nhỏ để có khử răng cưa. Chạy: python tools/make_icon.py
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

S = 1024
C = S // 2
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
SWEEP = 250  # phần đã hồi (độ, tính từ 12 giờ theo chiều kim đồng hồ)


def vertical_gradient(size, top, bottom):
    img = Image.new("RGBA", size)
    draw = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / (size[1] - 1)
        draw.line([(0, y), (size[0], y)],
                  fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    return img


def radial_gradient(radius, inner, outer):
    img = Image.new("RGBA", (radius * 2, radius * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for r in range(radius, 0, -2):
        t = r / radius
        color = tuple(int(a + (b - a) * t) for a, b in zip(inner, outer)) + (255,)
        draw.ellipse([radius - r, radius - r, radius + r, radius + r], fill=color)
    return img


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # nền: ô vuông bo góc, xanh đen kiểu hextech
    bg = vertical_gradient((S, S), (16, 34, 56), (4, 9, 18))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([16, 16, S - 16, S - 16], radius=210, fill=255)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), mask)
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle([16, 16, S - 16, S - 16], radius=210, outline=(200, 170, 110, 255),
                           width=14)

    # mặt đồng hồ: gradient xanh ngọc
    R = 360
    face = radial_gradient(R, (90, 230, 220), (0, 70, 120))
    icon.alpha_composite(face, (C - R, C - R))

    # phần chưa hồi: phủ tối giống icon phép trong game
    shade = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shade).pieslice([C - R, C - R, C + R, C + R], start=-90 + SWEEP, end=270,
                                   fill=(3, 8, 16, 170))
    icon.alpha_composite(shade)

    # tia chớp (Flash) ở giữa, có bóng đổ
    bolt = [(585, 150), (355, 560), (500, 560), (430, 880), (690, 440), (548, 440), (655, 150)]
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(x + 14, y + 18) for x, y in bolt], fill=(0, 0, 0, 160))
    icon.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    draw = ImageDraw.Draw(icon)
    draw.polygon(bolt, fill=(255, 244, 205, 255), outline=(120, 85, 30, 255), width=10)

    # kim đồng hồ ở mép phần đã hồi
    a = math.radians(SWEEP)
    end = (C + R * math.sin(a), C - R * math.cos(a))
    draw.line([(C, C), end], fill=(245, 225, 160, 255), width=18)

    # viền vàng quanh mặt đồng hồ
    draw.ellipse([C - R - 18, C - R - 18, C + R + 18, C + R + 18],
                 outline=(200, 170, 110, 255), width=40)
    draw.ellipse([C - R - 30, C - R - 30, C + R + 30, C + R + 30],
                 outline=(240, 230, 210, 255), width=6)

    small = icon.resize((256, 256), Image.LANCZOS)
    small.save(os.path.join(OUT_DIR, "icon.png"))
    small.save(os.path.join(OUT_DIR, "icon.ico"),
               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Đã tạo", os.path.normpath(os.path.join(OUT_DIR, "icon.ico")))


if __name__ == "__main__":
    main()
