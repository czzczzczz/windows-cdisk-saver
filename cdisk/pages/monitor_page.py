# -*- coding: utf-8 -*-
"""监控页：谁在往 C 盘写东西 + 两次快照对比谁在长胖。"""
from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import messagebox, ttk

from ..ui import (ACCENT, BG, CARD, GREEN, MUTED, ORANGE, RED, SUB, TEXT, button,
                  card, label, run_async, tree, F_BODY, F_H1, F_SMALL, F_TITLE)
from ..util import human, open_in_explorer
from ..watch import (ACT_LABEL, Watcher, default_roots, diff_snapshots,
                     load_snapshots, save_snapshot, take_snapshot)

SIZE_FILTERS = [("全部", 0), ("≥ 1 MB", 1 << 20), ("≥ 10 MB", 10 << 20),
                ("≥ 100 MB", 100 << 20)]


def bucket_of(path: str) -> str:
    """把文件路径归到「哪个软件的目录」，用于写入排行。"""
    parts = path.split("\\")
    low = [x.lower() for x in parts]
    if "appdata" in low:
        i = low.index("appdata")
        if i + 2 < len(parts):
            return "\\".join(parts[i:i + 3])
    if "documents" in low:
        i = low.index("documents")
        if i + 1 < len(parts):
            return "\\".join(parts[i:i + 2])
    if "programdata" in low:
        i = low.index("programdata")
        if i + 1 < len(parts):
            return "\\".join(parts[i:i + 2])
    return "\\".join(parts[:3])


def app_dir_of(path: str) -> str:
    """从文件路径推断出「该软件的数据目录」的完整路径，用于一键迁移。"""
    home = os.environ.get("USERPROFILE", "")
    parts = path.split("\\")
    low = [x.lower() for x in parts]
    if "appdata" in low:
        i = low.index("appdata")
        if i + 2 < len(parts):
            return "\\".join(parts[:i + 3])
    if "documents" in low:
        i = low.index("documents")
        if i + 1 < len(parts):
            return "\\".join(parts[:i + 2])
    if "programdata" in low:
        i = low.index("programdata")
        if i + 1 < len(parts):
            return "\\".join(parts[:i + 2])
    if home and path.lower().startswith(home.lower() + "\\"):
        rest = path[len(home) + 1:].split("\\")
        if rest and rest[0].startswith("."):
            return os.path.join(home, rest[0])
    return os.path.dirname(path)


class MonitorPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.watcher = None
        self.rows = {}
        self.path_size = {}
        self.buckets = {}
        self.total_added = 0
        self.acc = 0
        self.busy = False
        self._tick_n = 0
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        pad = 22
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=pad, pady=(18, 8))
        label(head, "C 盘写入监控", F_TITLE, TEXT, BG).pack(side="left")
        label(head, "实时看谁在往 C 盘写文件，或用快照对比找出「偷偷长胖」的目录",
              F_SMALL, MUTED, BG).pack(side="left", padx=12)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=pad, pady=(0, 14))

        # ---------------- 实时
        t1 = tk.Frame(nb, bg=BG)
        nb.add(t1, text="  实时监听  ")
        bar = tk.Frame(t1, bg=BG)
        bar.pack(fill="x", pady=8)
        self.btn_watch = button(bar, "开始监听", self.toggle_watch)
        self.btn_watch.pack(side="left")
        button(bar, "清空", self.clear_live, "ghost").pack(side="left", padx=8)
        button(bar, "迁移选中目录", self.migrate_selected_dir, "soft").pack(side="left")
        label(bar, "只看", F_SMALL, MUTED, BG).pack(side="left", padx=(12, 4))
        self.var_filter = tk.StringVar(value=SIZE_FILTERS[1][0])
        cb = ttk.Combobox(bar, textvariable=self.var_filter, width=8, state="readonly",
                          values=[s[0] for s in SIZE_FILTERS])
        cb.pack(side="left")
        self.lbl_live = label(bar, "未启动", F_SMALL, MUTED, BG)
        self.lbl_live.pack(side="right")

        c = card(t1, padx=0, pady=0)
        c.pack(fill="both", expand=True)
        cols = [("t", "时间"), ("act", "动作"), ("size", "体积"), ("path", "文件路径")]
        frame, self.live_tree = tree(c.inner, cols, [80, 60, 90, 720], height=18,
                                     stretch=[False, False, False, True])
        frame.pack(fill="both", expand=True)
        self.live_tree.bind("<Double-1>", self._open_live)

        # 写入排行（按软件目录聚合）
        rk = tk.Frame(t1, bg=BG)
        rk.pack(fill="x", pady=(10, 0))
        label(rk, "写入排行", F_H1, TEXT, BG).pack(side="left")
        label(rk, "按软件目录聚合，谁在偷偷占 C 盘一目了然", F_SMALL, MUTED, BG).pack(
            side="left", padx=8)
        rc = card(t1, padx=0, pady=0)
        rc.pack(fill="x", pady=(4, 0))
        frame3, self.rank_tree = tree(rc.inner, [("dir", "目录"), ("size", "累计写入")],
                                      [640, 140], height=5, stretch=[True, False])
        frame3.pack(fill="x")

        # ---------------- 快照
        t2 = tk.Frame(nb, bg=BG)
        nb.add(t2, text="  快照对比  ")
        bar2 = tk.Frame(t2, bg=BG)
        bar2.pack(fill="x", pady=8)
        self.btn_snap = button(bar2, "拍一张快照", self.snap)
        self.btn_snap.pack(side="left")
        self.btn_diff = button(bar2, "与上一次对比", self.do_diff, "soft")
        self.btn_diff.pack(side="left", padx=8)
        self.lbl_snap = label(bar2, "尚无快照", F_SMALL, MUTED, BG)
        self.lbl_snap.pack(side="right")

        c2 = card(t2, padx=0, pady=0)
        c2.pack(fill="both", expand=True)
        cols2 = [("d", "变化"), ("size", "当前体积"), ("path", "目录")]
        frame2, self.diff_tree = tree(c2.inner, cols2, [110, 110, 700], height=18,
                                      stretch=[False, False, True])
        frame2.pack(fill="both", expand=True)
        self.diff_tree.bind("<Double-1>", self._open_diff)
        self._refresh_snap_label()

    # ------------------------------------------------------------------ 实时
    def toggle_watch(self):
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
            self.btn_watch.configure(text="开始监听")
            self.lbl_live.configure(text="已停止", fg=MUTED)
            return
        roots = self.app.svc.watch_roots or default_roots()
        roots = [r for r in roots if os.path.isdir(r)]
        if not roots:
            messagebox.showerror("错误", "没有可监听的目录")
            return
        self.watcher = Watcher(on_error=lambda m: self.app.post(
            lambda: self.lbl_live.configure(text=m, fg=ORANGE)))
        n = sum(1 for r in roots if self.watcher.add_root(r))
        self.btn_watch.configure(text="停止监听")
        self.lbl_live.configure(text=f"监听中 · {n} 个根目录", fg=GREEN)
        self._poll()

    def _poll(self):
        if not self.watcher:
            return
        events = self.watcher.drain(300)
        if events:
            self._add_events(events)
        self._tick_n += 1
        if self._tick_n % 3 == 0:
            self._refresh_rank()
        self.after(400, self._poll)

    def _refresh_rank(self):
        top = sorted(self.buckets.items(), key=lambda kv: kv[1], reverse=True)[:5]
        self.rank_tree.delete(*self.rank_tree.get_children())
        for i, (d, sz) in enumerate(top):
            self.rank_tree.insert("", "end", values=(d, human(sz)),
                                  tags=("bad",) if sz > 500 << 20 else
                                  (("even",) if i % 2 else ()))

    def _min_size(self):
        for name, v in SIZE_FILTERS:
            if name == self.var_filter.get():
                return v
        return 0

    def _add_events(self, events):
        mn = self._min_size()
        for e in events:
            path = e["path"]
            prev = self.path_size.get(path, 0)
            if e["size"] > prev:
                self.path_size[path] = e["size"]
                delta = e["size"] - prev
                b = bucket_of(path)
                self.buckets[b] = self.buckets.get(b, 0) + delta
                self.total_added += delta
            if e["size"] < mn:
                continue
            self.acc += e["size"]
            old = self.rows.get(path)
            if old and self.live_tree.exists(old):
                self.live_tree.set(old, "size", human(e["size"]))
                continue
            iid = self.live_tree.insert("", 0, values=(
                time.strftime("%H:%M:%S", time.localtime(e["t"])),
                ACT_LABEL.get(e["act"], "?"), human(e["size"]), path))
            self.rows[path] = iid
            if len(self.rows) > 3000:
                self.clear_live()
        self.lbl_live.configure(
            text=f"监听中 · 累计写入 {human(self.total_added)}", fg=GREEN)

    def clear_live(self):
        self.live_tree.delete(*self.live_tree.get_children())
        self.rank_tree.delete(*self.rank_tree.get_children())
        self.rows.clear()
        self.path_size.clear()
        self.buckets.clear()
        self.total_added = 0

    def _open_live(self, _):
        sel = self.live_tree.selection()
        if not sel:
            return
        p = self.live_tree.item(sel[0], "values")[3]
        open_in_explorer(p)

    def migrate_selected_dir(self):
        """把选中那条记录所属的软件目录整体迁走。"""
        sel = self.live_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表里点选一条记录")
            return
        p = self.live_tree.item(sel[0], "values")[3]
        d = app_dir_of(p)
        if not os.path.isdir(d):
            messagebox.showerror("错误", f"目录不存在：\n{d}")
            return
        self.app.custom_migrate(d)

    # ------------------------------------------------------------------ 快照
    def _refresh_snap_label(self):
        snaps = load_snapshots()
        if not snaps:
            self.lbl_snap.configure(text="尚无快照")
        else:
            self.lbl_snap.configure(
                text=f"共 {len(snaps)} 张快照 · 最近：{snaps[0]['time']}")

    def snap(self):
        if self.busy:
            return
        self.busy = True
        self.btn_snap.configure(state="disabled")
        self.lbl_snap.configure(text="正在扫描目录体积，请稍候 …")

        def prog(n, p):
            self.app.post(lambda: self.lbl_snap.configure(
                text=f"扫描中：{n:,} 个文件 · {os.path.dirname(p)[:60]}"))

        def work():
            data = take_snapshot(progress=prog)
            save_snapshot(data)
            return len(data)

        def done(n):
            self.busy = False
            self.btn_snap.configure(state="normal")
            self._refresh_snap_label()
            self.lbl_snap.configure(text=f"快照完成，记录 {n:,} 个目录 · {time.strftime('%H:%M:%S')}")
            self.do_diff()

        run_async(self.app.post, work, done,
                  on_error=lambda e: (self.busy, self.btn_snap.configure(state="normal"),
                                      self._refresh_snap_label(),
                                      messagebox.showerror("失败", str(e))))

    def do_diff(self):
        snaps = load_snapshots()
        if len(snaps) < 2:
            self.lbl_snap.configure(text="至少需要两张快照才能对比，请再拍一张")
            return
        new, old = snaps[0]["data"], snaps[1]["data"]
        grown, shrunk = diff_snapshots(old, new)
        self.diff_tree.delete(*self.diff_tree.get_children())
        for i, (d, p, o, n) in enumerate(grown):
            self.diff_tree.insert("", "end", values=(f"+{human(d)}", human(n), p),
                                  tags=("bad",) if d > 200 << 20 else
                                  (("even",) if i % 2 else ()))
        for d, p, o, n in shrunk:
            self.diff_tree.insert("", "end", values=(f"-{human(abs(d))}", human(n), p),
                                  tags=("ok",))
        self.lbl_snap.configure(
            text=f"{snaps[1]['time']}  →  {snaps[0]['time']}   增长目录 {len(grown)} 个")

    def _open_diff(self, _):
        sel = self.diff_tree.selection()
        if not sel:
            return
        p = self.diff_tree.item(sel[0], "values")[2]
        open_in_explorer(p)

    # ------------------------------------------------------------------ 生命周期
    def on_show(self):
        self._refresh_snap_label()

    def destroy(self):
        if self.watcher:
            self.watcher.stop()
        super().destroy()
