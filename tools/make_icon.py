# -*- coding: utf-8 -*-
"""生成应用图标 assets/app.ico。"""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "assets", "app.ico")


def draw(size=512):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 圆角底
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=(37, 99, 235, 255))
    # 顶部高光
    d.rounded_rectangle([0, 0, size - 1, int(size * 0.5)], radius=r,
                        fill=(59, 130, 246, 255))
    d.rectangle([0, int(size * 0.32), size - 1, int(size * 0.5)], fill=(59, 130, 246, 255))

    # 白色 C
    m = size * 0.24
    box = [m, m * 0.95, size - m, size - m * 0.95]
    w = int(size * 0.105)
    d.arc(box, start=42, end=318, fill=(255, 255, 255, 255), width=w)

    # 向右的箭头（数据搬出去）
    cy = size * 0.5
    x0, x1 = size * 0.40, size * 0.74
    d.line([x0, cy, x1, cy], fill=(255, 255, 255, 255), width=int(size * 0.072))
    ah = size * 0.085
    d.polygon([(x1 + ah * 0.55, cy), (x1 - ah * 0.55, cy - ah),
               (x1 - ah * 0.55, cy + ah)], fill=(255, 255, 255, 255))
    return img


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    big = draw(512)
    big.save(OUT, format="ICO",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.resize((256, 256), Image.LANCZOS).save(
        os.path.join(os.path.dirname(OUT), "app.png"))
    print("icon ->", OUT)
