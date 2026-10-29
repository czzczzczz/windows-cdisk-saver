# -*- coding: utf-8 -*-
"""无依赖截图：找到指定标题的窗口并保存为 PNG（GDI BitBlt + zlib）。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
import zlib

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


def find_window(title_part: str):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_part in buf.value and user32.IsWindowVisible(hwnd):
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return found


def capture(x, y, w, h, out, max_w=1400):
    hdc = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, x, y, 0x00CC0020)

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)

    step = max(1, w // max_w) if w > max_w else 1
    ow, oh = w // step, h // step
    px = buf.raw
    raw = bytearray()
    for row in range(oh):
        src = row * step * w * 4
        raw.append(0)
        for col in range(ow):
            o = src + col * step * 4
            raw += bytes((px[o + 2], px[o + 1], px[o]))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", ow, oh, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    png += chunk(b"IEND", b"")
    with open(out, "wb") as f:
        f.write(png)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)
    return ow, oh


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    title = sys.argv[1] if len(sys.argv) > 1 else "C 盘空间管家"
    out = sys.argv[2] if len(sys.argv) > 2 else r"D:\拯救C盘\_shot.png"
    wins = find_window(title)
    if not wins:
        print("NOTFOUND")
        sys.exit(1)
    best, best_area = None, -1
    for hwnd, name in wins:
        rr = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rr))
        area = (rr.right - rr.left) * (rr.bottom - rr.top)
        print(f"  cand {name!r} {rr.right-rr.left}x{rr.bottom-rr.top}")
        if area > best_area:
            best, best_area = (hwnd, name), area
    hwnd, name = best
    user32.ShowWindow(hwnd, 9)   # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.7)
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    size = capture(r.left, r.top, w, h, out)
    print(f"OK {name!r} rect={w}x{h} -> {out} ({size[0]}x{size[1]})")
