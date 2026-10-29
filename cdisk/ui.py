# -*- coding: utf-8 -*-
"""界面基础组件与主题。"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

BG = "#f4f6f9"
CARD = "#ffffff"
BORDER = "#e3e8ef"
TEXT = "#111827"
MUTED = "#6b7280"
SUB = "#9aa4b2"
ACCENT = "#2563eb"
ACCENT_DK = "#1d4ed8"
ACCENT_BG = "#eef3ff"
GREEN = "#16a34a"
RED = "#dc2626"
ORANGE = "#ea580c"
YELLOW = "#ca8a04"

FONT = "Microsoft YaHei UI"
F_TITLE = (FONT, 16, "bold")
F_H1 = (FONT, 12, "bold")
F_BODY = (FONT, 10)
F_SMALL = (FONT, 9)
F_MONO = ("Consolas", 9)


def setup_theme(root: tk.Tk):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(bg=BG)
    style.configure(".", font=F_BODY, background=BG, foreground=TEXT)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=BG, foreground=TEXT, font=F_BODY)
    style.configure("Card.TLabel", background=CARD, foreground=TEXT)
    style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=F_SMALL)
    style.configure("H1.TLabel", background=BG, foreground=TEXT, font=F_TITLE)
    style.configure("H2.TLabel", background=CARD, foreground=TEXT, font=F_H1)

    style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                    rowheight=26, borderwidth=0, font=F_BODY)
    style.configure("Treeview.Heading", background="#f8fafc", foreground=MUTED,
                    font=(FONT, 9, "bold"), relief="flat", borderwidth=0)
    style.map("Treeview", background=[("selected", ACCENT_BG)],
              foreground=[("selected", ACCENT_DK)])
    style.map("Treeview.Heading", background=[("active", "#eef2f7")])

    style.configure("Thin.Horizontal.TProgressbar", troughcolor="#eef1f5",
                    background=ACCENT, borderwidth=0, thickness=8)
    style.configure("TEntry", fieldbackground=CARD, borderwidth=1, relief="flat")
    style.configure("TCombobox", fieldbackground=CARD, background=CARD)
    style.configure("TCheckbutton", background=CARD, foreground=TEXT, font=F_BODY)
    style.map("TCheckbutton", background=[("active", CARD)])
    style.configure("TSeparator", background=BORDER)
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=[0, 0, 0, 0])
    style.configure("TNotebook.Tab", background="#e9edf3", foreground=MUTED,
                    padding=[16, 7], borderwidth=0, font=(FONT, 9))
    style.map("TNotebook.Tab",
              background=[("selected", CARD)],
              foreground=[("selected", ACCENT_DK)],
              expand=[("selected", (0, 0, 0, 0))])
    return style


# ------------------------------------------------------------------ 控件工厂
def button(parent, text, command=None, kind="primary", width=None, bg=None):
    palette = {
        "primary": (ACCENT, "#ffffff", ACCENT_DK),
        "ghost": ("#ffffff", TEXT, "#f3f4f6"),
        "danger": ("#fff1f0", RED, "#ffe4e1"),
        "soft": (ACCENT_BG, ACCENT_DK, "#e0e9ff"),
    }
    b, f, a = palette.get(kind, palette["primary"])
    if bg:
        b = bg
    btn = tk.Button(
        parent, text=text, command=command, font=F_BODY,
        bg=b, fg=f, activebackground=a, activeforeground=f,
        relief="flat", bd=0, cursor="hand2", padx=14, pady=6,
        highlightthickness=0,
    )
    if width:
        btn.configure(width=width)
    return btn


def card(parent, padx=16, pady=14):
    outer = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    inner = tk.Frame(outer, bg=CARD)
    inner.pack(fill="both", expand=True, padx=padx, pady=pady)
    outer.inner = inner  # type: ignore[attr-defined]
    return outer


def label(parent, text, font=F_BODY, fg=TEXT, bg=CARD, **kw):
    return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, **kw)


def entry(parent, textvariable=None, width=40):
    e = tk.Entry(parent, textvariable=textvariable, font=F_BODY, bg="#ffffff",
                 fg=TEXT, relief="flat", highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT, insertbackground=TEXT)
    if width:
        e.configure(width=width)
    return e


class ScrollFrame(tk.Frame):
    """带垂直滚动条的容器。"""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind_all("<MouseWheel>", self._wheel, add="+")

    def _on_body(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def _wheel(self, e):
        try:
            if self.winfo_containing(e.x_root, e.y_root) is None:
                return
            self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except Exception:
            pass


class Bar(tk.Frame):
    """自绘百分比条。"""

    def __init__(self, parent, width=520, height=10, color=ACCENT, bg="#eef1f5"):
        super().__init__(parent, bg=bg, height=height, width=width)
        self.pack_propagate(False)
        self._bar = tk.Frame(self, bg=color)
        self._bar.place(x=0, y=0, relheight=1, relwidth=0)
        self._color = color
        self._bg = bg

    def set(self, ratio: float, color=None):
        ratio = max(0.0, min(1.0, ratio))
        self._bar.configure(bg=color or self._color)
        self._bar.place_configure(relwidth=ratio)


def tree(parent, columns, widths=None, height=12, anchors=None, stretch=None):
    """创建带竖向滚动条的 Treeview，返回 (container, tree)。"""
    frame = tk.Frame(parent, bg=CARD)
    tv = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings",
                      height=height, selectmode="extended")
    for i, (key, title) in enumerate(columns):
        tv.heading(key, text=title, anchor="w")
        w = widths[i] if widths else 120
        a = anchors[i] if anchors else "w"
        st = stretch[i] if stretch else False
        tv.column(key, width=w, anchor=a, stretch=st, minwidth=60)
    vs = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=vs.set)
    vs.pack(side="right", fill="y")
    tv.pack(side="left", fill="both", expand=True)
    tv.tag_configure("even", background="#fbfcfe")
    tv.tag_configure("warn", foreground=ORANGE)
    tv.tag_configure("bad", foreground=RED)
    tv.tag_configure("ok", foreground=GREEN)
    tv.tag_configure("muted", foreground=MUTED)
    return frame, tv


# ------------------------------------------------------------------ 线程辅助
class Dispatcher:
    """把后台线程的 UI 更新安全地转回主线程执行。"""

    def __init__(self, root, interval=60):
        self.root = root
        self.q = queue.Queue()
        self.interval = interval
        self._tick()

    def post(self, fn):
        self.q.put(fn)

    def _tick(self):
        try:
            for _ in range(300):
                fn = self.q.get_nowait()
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass
        except queue.Empty:
            pass
        self.root.after(self.interval, self._tick)


def run_async(post, fn, on_done=None, on_error=None):
    """在后台线程执行 fn()，结果通过 post 回到主线程。"""
    def worker():
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            if on_error:
                post(lambda e=exc: on_error(e))
            return
        if on_done:
            post(lambda r=result: on_done(r))
    threading.Thread(target=worker, daemon=True).start()


def status_pill(parent, text, fg=ACCENT, bg=ACCENT_BG):
    return tk.Label(parent, text=text, font=F_SMALL, fg=fg, bg=bg, padx=8, pady=2)
