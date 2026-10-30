# -*- coding: utf-8 -*-
"""生成应用图标 assets/app.ico（多尺寸）。

设计：圆角渐变底 + 白色 C 形环 + 一道从环内穿出的箭头，表达「把数据从 C 盘搬出去」。
超采样后降采样，保证小尺寸下边缘干净。
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "assets", "app.ico")
PNG = os.path.join(HERE, "assets", "app.png")

S = 1024
W = S * 2                   # 超采样

TOP = (0x3B, 0x82, 0xF6)    # 亮蓝
BOT = (0x1D, 0x4E, 0xD8)    # 深蓝
WHITE = (255, 255, 255, 255)


def rounded_gradient(w, h, radius):
    grad = Image.new("RGB", (w, h))
    gd = ImageDraw.Draw(grad)
    for y in range(h):
        t = (y / max(1, h - 1)) ** 0.85
        c = tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3))
        gd.line([(0, y), (w, y)], fill=c)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1],
                                           radius=radius, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def draw_icon():
    img = rounded_gradient(W, W, int(W * 0.225))

    # 顶部高光
    hl = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(hl).rounded_rectangle(
        [int(W * 0.03), int(W * 0.03), W - int(W * 0.03), int(W * 0.55)],
        radius=int(W * 0.20), fill=(255, 255, 255, 24))
    img = Image.alpha_composite(img, hl)
    d = ImageDraw.Draw(img)

    cx = cy = W / 2

    # C 形环：平头收尾，小尺寸下更接近字母 C 的形态
    r = W * 0.300
    lw = int(W * 0.110)
    d.arc([cx - r, cy - r, cx + r, cy + r], start=42, end=318, fill=WHITE, width=lw)

    # 穿出的箭头
    shaft_w = int(W * 0.088)
    x0, x1 = W * 0.455, W * 0.720
    d.rounded_rectangle([x0, cy - shaft_w / 2, x1, cy + shaft_w / 2],
                        radius=shaft_w / 2, fill=WHITE)
    head_w, head_h = W * 0.090, W * 0.150
    d.polygon([(x1 + head_w, cy), (x1 - head_w * 0.35, cy - head_h),
               (x1 - head_w * 0.35, cy + head_h)], fill=WHITE)

    return img.resize((S, S), Image.LANCZOS)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    big = draw_icon()

    # 带柔和投影的版本，用于文档展示
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    a = big.split()[3].filter(ImageFilter.GaussianBlur(S * 0.022))
    shadow.putalpha(a.point(lambda v: int(v * 0.30)))
    base = Image.alpha_composite(Image.new("RGBA", (S, S), (0, 0, 0, 0)), shadow)
    Image.alpha_composite(base, big).save(PNG)

    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    big.save(OUT, format="ICO", sizes=sizes)
    print("图标已生成:", OUT, os.path.getsize(OUT), "bytes")
