# -*- coding: utf-8 -*-
"""历史页：所有迁移记录，可随时还原。"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..migrate import load_records, rollback, update_record
from ..ui import (ACCENT, BG, CARD, GREEN, MUTED, ORANGE, RED, SUB, TEXT, button,
                  card, label, run_async, tree, F_BODY, F_H1, F_SMALL, F_TITLE)
from ..util import human, is_admin, open_in_explorer, relaunch_as_admin, save_json

STATUS = {"done": ("已迁移", GREEN), "rolledback": ("已还原", MUTED),
          "failed": ("失败", RED)}


class HistoryPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.rows = {}
        self.busy = False
        self._build()

    def _build(self):
        pad = 22
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=pad, pady=(18, 8))
        label(head, "迁移记录", F_TITLE, TEXT, BG).pack(side="left")
        label(head, "每条迁移都可逆：还原会把数据搬回 C 盘并删除联接",
              F_SMALL, MUTED, BG).pack(side="left", padx=12)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=pad, pady=(0, 8))
        button(bar, "刷新", self.refresh, "ghost").pack(side="left")
        button(bar, "打开目标目录", self.open_dst, "ghost").pack(side="left", padx=8)
        self.btn_rb = button(bar, "还原选中", self.do_rollback, "danger")
        self.btn_rb.pack(side="right")
        self.lbl = label(bar, "", F_SMALL, MUTED, BG)
        self.lbl.pack(side="right", padx=12)

        c = card(self, padx=0, pady=0)
        c.pack(fill="both", expand=True, padx=pad, pady=(0, 14))
        cols = [("time", "时间"), ("name", "项目"), ("src", "原位置"),
                ("dst", "现位置"), ("size", "体积"), ("status", "状态")]
        frame, self.tree = tree(c.inner, cols, [128, 140, 275, 275, 78, 66],
                                height=18, stretch=[False, True, True, True, False, False])
        frame.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.open_dst())

    # ------------------------------------------------------------------
    def on_show(self):
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        recs = load_records()
        total = 0
        for i, r in enumerate(recs):
            txt, color = STATUS.get(r.get("status", ""), ("?", MUTED))
            iid = self.tree.insert("", "end", values=(
                r.get("time", ""), r.get("name", ""), r.get("src", ""),
                r.get("dst", ""), human(r.get("bytes", 0)), txt),
                tags=("even",) if i % 2 else ())
            self.rows[iid] = r
            if r.get("status") == "done":
                total += r.get("bytes", 0)
        self.lbl.configure(text=f"{len(recs)} 条记录 · 累计释放 {human(total)}")

    def open_dst(self):
        sel = self.tree.selection()
        if not sel:
            return
        r = self.rows.get(sel[0])
        if r:
            p = r.get("dst", "")
            open_in_explorer(p if os.path.exists(p) else os.path.dirname(p))

    def do_rollback(self):
        if self.busy:
            return
        sel = [self.rows.get(i) for i in self.tree.selection()]
        recs = [r for r in sel if r and r.get("status") == "done"]
        if not recs:
            messagebox.showinfo("提示", "请选择状态为「已迁移」的记录")
            return
        if not messagebox.askyesno("确认还原",
                                   f"将把 {len(recs)} 个目录搬回 C 盘，请确认空间足够。"):
            return
        self.busy = True
        self.btn_rb.configure(state="disabled")

        def work():
            ok = 0
            for r in recs:
                good, msg = rollback(r)
                ok += 1 if good else 0
                self.app.post(lambda g=good, m=msg, rr=r:
                              self.lbl.configure(text=f"{rr['name']}：{m}"))
            return ok

        def done(ok):
            self.busy = False
            self.btn_rb.configure(state="normal")
            self.refresh()
            self.app.on_targets_updated()
            messagebox.showinfo("完成", f"成功还原 {ok}/{len(recs)} 个目录")

        run_async(self.app.post, work, done,
                  on_error=lambda e: (self.busy, self.btn_rb.configure(state="normal"),
                                      messagebox.showerror("失败", str(e))))
