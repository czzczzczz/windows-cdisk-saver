# -*- coding: utf-8 -*-
"""C 盘空间管家 —— 主窗口。"""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from cdisk import ui
from cdisk.migrate import Job, is_lock_error, migrate_job
from cdisk.pages.analyze import AnalyzePage
from cdisk.pages.clean_page import CleanPage
from cdisk.pages.history import HistoryPage
from cdisk.pages.migrate_page import MigratePage
from cdisk.pages.monitor_page import MonitorPage
from cdisk.pages.overview import OverviewPage
from cdisk.pages.unlock import show_unlock
from cdisk.service import Service
from cdisk.ui import (ACCENT, ACCENT_BG, ACCENT_DK, BG, BORDER, CARD, GREEN, MUTED,
                      ORANGE, SUB, TEXT, Dispatcher, label, run_async)
from cdisk.util import human, is_admin, relaunch_as_admin

APP_TITLE = "C 盘空间管家"
VERSION = "1.0.0"

NAV = [
    ("overview", "概览", "◎"),
    ("migrate", "缓存迁移", "⇄"),
    ("analyze", "空间分析", "▤"),
    ("monitor", "写入监控", "◉"),
    ("clean", "系统清理", "✦"),
    ("history", "迁移记录", "≡"),
]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.svc = Service()
        self.post = Dispatcher(root).post
        self.pages = {}
        self.nav_buttons = {}
        self.current = None
        self._scanning = False

        root.title(f"{APP_TITLE} v{VERSION}")
        root.geometry("1200x780")
        root.minsize(1040, 660)
        self._center()
        ui.setup_theme(root)
        self._build()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.open_page("overview")
        root.after(300, self.refresh_targets)

    # ------------------------------------------------------------------ 布局
    def _center(self):
        self.root.update_idletasks()
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
            work_w = rect.right - rect.left
            work_h = rect.bottom - rect.top
            left, top = rect.left, rect.top
        except Exception:
            work_w, work_h, left, top = 1920, 1040, 0, 0
        w = min(1220, work_w - 30)
        h = min(800, work_h - 30)
        x = left + max(0, (work_w - w) // 2)
        y = top + max(0, (work_h - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _build(self):
        # 状态栏先占位，避免被主区域挤掉
        self.statusbar = tk.Frame(self.root, bg="#ffffff", height=26)
        self.statusbar.pack(side="bottom", fill="x")
        self.statusbar.pack_propagate(False)
        tk.Frame(self.root, bg=BORDER, height=1).pack(side="bottom", fill="x")
        self.lbl_status = tk.Label(self.statusbar, text="就绪", font=(ui.FONT, 8),
                                   bg="#ffffff", fg=MUTED, anchor="w")
        self.lbl_status.pack(side="left", padx=12)
        self.lbl_right = tk.Label(self.statusbar, text="", font=(ui.FONT, 8),
                                  bg="#ffffff", fg=SUB, anchor="e")
        self.lbl_right.pack(side="right", padx=12)

        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True)

        side = tk.Frame(shell, bg="#ffffff", width=196)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(shell, bg=BORDER, width=1).pack(side="left", fill="y")

        brand = tk.Frame(side, bg="#ffffff")
        brand.pack(fill="x", pady=(20, 6), padx=18)
        label(brand, "C 盘空间管家", (ui.FONT, 12, "bold"), TEXT, "#ffffff").pack(anchor="w")
        label(brand, f"v{VERSION} · 让 C 盘喘口气", (ui.FONT, 8), SUB, "#ffffff").pack(anchor="w")

        nav = tk.Frame(side, bg="#ffffff")
        nav.pack(fill="x", pady=(14, 0))
        for key, name, icon in NAV:
            self._nav_item(nav, key, name, icon)

        bottom = tk.Frame(side, bg="#ffffff")
        bottom.pack(side="bottom", fill="x", pady=14, padx=12)
        self.lbl_admin = tk.Label(bottom, text="", font=(ui.FONT, 8), anchor="w",
                                  bg="#ffffff", fg=MUTED, wraplength=170, justify="left")
        self.lbl_admin.pack(fill="x")
        self.btn_admin = ui.button(bottom, "以管理员身份重启", self._elevate, "ghost")
        self.btn_admin.pack(fill="x", pady=(6, 0))
        self._refresh_admin_ui()

        self.content = tk.Frame(shell, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

        self.pages["overview"] = OverviewPage(self.content, self)
        self.pages["migrate"] = MigratePage(self.content, self)
        self.pages["analyze"] = AnalyzePage(self.content, self)
        self.pages["monitor"] = MonitorPage(self.content, self)
        self.pages["clean"] = CleanPage(self.content, self)
        self.pages["history"] = HistoryPage(self.content, self)

    def _nav_item(self, parent, key, name, icon):
        row = tk.Frame(parent, bg="#ffffff", cursor="hand2")
        row.pack(fill="x", padx=10, pady=1)
        ind = tk.Frame(row, bg="#ffffff", width=3)
        ind.pack(side="left", fill="y")
        inner = tk.Frame(row, bg="#ffffff")
        inner.pack(side="left", fill="x", expand=True, padx=(10, 8), pady=7)
        ic = tk.Label(inner, text=icon, font=(ui.FONT, 10), bg="#ffffff", fg=MUTED, width=2)
        ic.pack(side="left")
        tx = tk.Label(inner, text=name, font=(ui.FONT, 10), bg="#ffffff", fg=TEXT, anchor="w")
        tx.pack(side="left", fill="x", expand=True)

        def enter(_):
            if self.current != key:
                for w in (row, inner, ic, tx, ind):
                    w.configure(bg="#f6f8fb")

        def leave(_):
            if self.current != key:
                for w in (row, inner, ic, tx, ind):
                    w.configure(bg="#ffffff")

        for w in (row, inner, ic, tx):
            w.bind("<Button-1>", lambda e, k=key: self.open_page(k))
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
        self.nav_buttons[key] = (row, inner, ic, tx, ind)

    def open_page(self, key):
        if key not in self.pages:
            return
        if self.current and self.current in self.pages:
            self.pages[self.current].pack_forget()
        self.current = key
        page = self.pages[key]
        page.pack(fill="both", expand=True)
        for k, widgets in self.nav_buttons.items():
            row, inner, ic, tx, ind = widgets
            on = k == key
            bg = ACCENT_BG if on else "#ffffff"
            for w in (row, inner, ic, tx, ind):
                w.configure(bg=bg)
            ind.configure(bg=ACCENT if on else bg)
            ic.configure(fg=ACCENT if on else MUTED)
            tx.configure(fg=ACCENT_DK if on else TEXT)
        if hasattr(page, "on_show"):
            page.on_show()

    # ------------------------------------------------------------------ 状态
    def set_status(self, text):
        self.lbl_status.configure(text=text)

    def _refresh_admin_ui(self):
        if is_admin():
            self.lbl_admin.configure(text="管理员权限 · 可处理系统级目录", fg=GREEN)
            self.btn_admin.pack_forget()
        else:
            self.lbl_admin.configure(
                text="普通权限：可迁移用户目录，系统目录需管理员", fg=ORANGE)
            self.btn_admin.pack(fill="x", pady=(6, 0))

    def _elevate(self):
        if relaunch_as_admin():
            self._on_close()

    def _on_close(self):
        try:
            if "monitor" in self.pages:
                self.pages["monitor"].destroy()
        except Exception:
            pass
        self.root.destroy()

    # ------------------------------------------------------------------ 数据
    def refresh_targets(self):
        if self._scanning:
            return
        self._scanning = True
        self.set_status("正在扫描可迁移目录 …")

        def prog(msg):
            self.post(lambda: self.set_status(msg))

        def work():
            return self.svc.scan_targets(progress=prog)

        def done(rows):
            self._scanning = False
            self.on_targets_updated()
            self.set_status("扫描完成")
            self.start_discovery()

        run_async(self.post, work, done,
                  on_error=lambda e: (self.set_status(f"扫描失败：{e}"),
                                      setattr(self, "_scanning", False)))

    def start_discovery(self):
        """在内置目标之外，再扫一遍用户目录，找出没被收录的大目录。"""
        if self.svc.discovering:
            return
        self.svc.discovering = True
        ov = self.pages.get("overview")
        if ov:
            ov.refresh()          # 先把「正在发现 …」显示出来

        def prog(n, p):
            self.post(lambda: self.set_status(
                f"正在发现未收录的大目录：{n:,} 个文件 · {os.path.dirname(p)[:60]}"))

        def work():
            return self.svc.discover_big(progress=prog)

        def done(rows):
            self.set_status(f"发现 {len(rows)} 个未收录的大目录")
            self.on_targets_updated()

        run_async(self.post, work, done,
                  on_error=lambda e: self.set_status(f"发现失败：{e}"))

    def on_targets_updated(self):
        page = self.pages.get("overview")
        if page:
            page.refresh()
        mp = self.pages.get("migrate")
        if mp is not None and self.current == "migrate" and not mp.busy and self.svc.tinfo:
            mp._fill()
        self.lbl_right.configure(
            text=f"可迁移 {human(self.svc.migratable_bytes())} · "
                 f"落点 {self.svc.dest_root}")

    # ------------------------------------------------------------------ 快捷迁移
    def quick_migrate(self, row):
        self.open_page("migrate")
        self.pages["migrate"].migrate_targets([row["t"]])

    def custom_migrate(self, path, size=0):
        if not os.path.isdir(path):
            messagebox.showerror("错误", "目录不存在")
            return
        dst = os.path.join(self.svc.dest_root, "Custom", os.path.basename(path.rstrip("\\")))
        if not messagebox.askyesno(
                "迁移自定义目录",
                f"源目录：{path}\n目标目录：{dst}\n\n"
                "迁移后原路径会变成指向新位置的目录联接，程序照常访问。\n是否继续？"):
            return
        self.set_status("正在迁移 …")

        def stage(msg):
            self.post(lambda: self.set_status(msg))

        def prog(p):
            self.post(lambda: self.set_status(f"正在迁移 {path} · {p*100:.0f}%"))

        def work():
            job = Job(src=path, dst=dst, tid="custom", name=os.path.basename(path))
            job.scan()
            return migrate_job(job, progress=prog, stage=stage)

        def done(res):
            ok, msg, rec = res
            self.set_status(("✔ " if ok else "✘ ") + msg)
            if ok:
                messagebox.showinfo("完成", msg)
                self.refresh_targets()
            else:
                if is_lock_error(msg):
                    if messagebox.askyesno(
                            "文件被占用",
                            f"{msg}\n\n要不要查找并关闭占用它的程序？\n"
                            "（关闭前请先保存工作，未保存的数据会丢失）"):
                        show_unlock(self.root, self, [path],
                                    on_retry=lambda: self.custom_migrate(path))
                else:
                    messagebox.showerror("迁移失败", msg)

        run_async(self.post, work, done, on_error=lambda e: self.set_status(f"失败：{e}"))


def _set_window_icon(root):
    """窗口/任务栏图标。打包后资源在 _MEIPASS，源码运行则取项目 assets。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    ico = os.path.join(base, "assets", "app.ico")
    try:
        if os.path.exists(ico):
            root.iconbitmap(default=ico)
    except Exception:
        pass


def _install_error_hooks(root):
    """pythonw 没有控制台，回调里的异常会静默消失。这里兜住并弹窗 + 落盘。"""
    import time
    import traceback

    from cdisk.util import app_dir

    def report(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        path = os.path.join(app_dir(), "error.log")
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n{text}")
        except Exception:
            pass
        try:
            from tkinter import messagebox as mb
            mb.showerror("程序出错了",
                         f"{exc_type.__name__}: {exc}\n\n"
                         f"详细信息已写入：\n{path}\n\n"
                         "把这段内容发给我，能快速定位。")
        except Exception:
            pass

    root.report_callback_exception = report


def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    _install_error_hooks(root)
    _set_window_icon(root)
    page = ""
    for a in sys.argv[1:]:
        if a.startswith("--page="):
            page = a.split("=", 1)[1]
    app = App(root)
    if page:
        root.after(400, lambda: app.open_page(page))
    root.mainloop()


if __name__ == "__main__":
    main()
