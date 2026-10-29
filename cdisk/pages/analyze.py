# -*- coding: utf-8 -*-
"""空间分析页：找出 C 盘里到底是谁在吃空间，并可把任意大目录搬走。"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..migrate import Job, migrate_job
from ..scan import scan
from ..ui import (ACCENT, BG, CARD, GREEN, MUTED, ORANGE, RED, SUB, TEXT, Bar,
                  button, card, entry, label, run_async, tree, F_BODY, F_H1, F_SMALL,
                  F_TITLE)
from ..util import human, is_admin, open_in_explorer, relaunch_as_admin


class AnalyzePage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.node_of = {}
        self.root_node = None
        self.cancel = threading.Event()
        self.busy = False
        self.big = []
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        pad = 22
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=pad, pady=(18, 8))
        label(head, "空间分析", F_TITLE, TEXT, BG).pack(side="left")
        label(head, "扫描任意目录，按体积排序，找到元凶后可直接迁移",
              F_SMALL, MUTED, BG).pack(side="left", padx=12)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=pad, pady=(0, 8))
        self.var_path = tk.StringVar(value=os.environ.get("SystemDrive", "C:") + "\\")
        entry(bar, self.var_path, width=52).pack(side="left", ipady=3)
        button(bar, "选择", self._pick, "ghost").pack(side="left", padx=6)
        label(bar, "深度", F_SMALL, MUTED, BG).pack(side="left", padx=(10, 4))
        self.var_depth = tk.StringVar(value="3")
        ttk.Combobox(bar, textvariable=self.var_depth, width=4, state="readonly",
                     values=["1", "2", "3", "4"]).pack(side="left")
        self.btn_scan = button(bar, "开始扫描", self.start_scan)
        self.btn_scan.pack(side="left", padx=10)
        self.btn_stop = button(bar, "停止", self._stop, "ghost")
        self.btn_stop.pack(side="left")
        self.btn_stop.configure(state="disabled")
        self.btn_mig = button(bar, "迁移选中目录", self.migrate_node, "soft")
        self.btn_mig.pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=pad, pady=(0, 10))

        tab1 = tk.Frame(nb, bg=CARD)
        nb.add(tab1, text="  目录树  ")
        cols = [("name", "名称"), ("size", "体积"), ("pct", "占比"),
                ("files", "文件数"), ("path", "路径")]
        frame, self.tree = tree(tab1, cols, [300, 100, 80, 80, 420],
                                height=16, stretch=[True, False, False, False, True])
        self.tree.configure(show="tree headings")
        self.tree.column("#0", width=26, stretch=False)
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewOpen>>", self._on_open)
        self.tree.bind("<Double-1>", self._on_dbl)

        tab2 = tk.Frame(nb, bg=CARD)
        nb.add(tab2, text="  大文件  ")
        cols2 = [("size", "体积"), ("path", "路径")]
        frame2, self.big_tree = tree(tab2, cols2, [110, 700], height=16,
                                     stretch=[False, True])
        frame2.pack(fill="both", expand=True)
        self.big_tree.bind("<Double-1>", self._open_big)

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=pad, pady=(0, 14))
        self.pb = ttk.Progressbar(foot, style="Thin.Horizontal.TProgressbar",
                                  mode="determinate", maximum=100, value=0, length=240)
        self.pb.pack(side="left")
        self.lbl = label(foot, "选择目录后点击开始扫描", F_SMALL, MUTED, BG)
        self.lbl.pack(side="left", padx=12)

    # ------------------------------------------------------------------ 交互
    def _pick(self):
        d = filedialog.askdirectory(title="选择要分析的目录")
        if d:
            self.var_path.set(os.path.normpath(d))

    def on_show(self):
        pass

    def _stop(self):
        self.cancel.set()

    def start_scan(self):
        if self.busy:
            return
        path = self.var_path.get().strip().strip('"')
        if not os.path.isdir(path):
            messagebox.showerror("错误", "目录不存在")
            return
        depth = int(self.var_depth.get())
        self.busy = True
        self.cancel.clear()
        self.btn_scan.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.pb.start(12)
        self.tree.delete(*self.tree.get_children())
        self.big_tree.delete(*self.big_tree.get_children())
        self.node_of.clear()

        def prog(n, p):
            self.app.post(lambda: self.lbl.configure(
                text=f"已扫描 {n:,} 个文件 · {os.path.dirname(p)[:70]}"))

        def work():
            return scan(path, max_depth=depth, progress=prog, cancel=self.cancel)

        def done(res):
            self.root_node, self.big = res
            self.busy = False
            self.pb.stop()
            self.btn_scan.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.lbl.configure(text=f"扫描完成：{human(self.root_node.size)} · "
                                    f"{self.root_node.files:,} 个文件")
            self._fill_root()
            self._fill_big()

        run_async(self.app.post, work, done,
                  on_error=lambda e: (self.pb.stop(), self.btn_scan.configure(state="normal"),
                                      self.btn_stop.configure(state="disabled"),
                                      messagebox.showerror("扫描失败", str(e))))

    # ------------------------------------------------------------------ 填充
    def _fill_root(self):
        r = self.root_node
        if not r:
            return
        iid = self.tree.insert("", "end", text="▾", open=True, values=(
            r.name, human(r.size), "100%", f"{r.files:,}", r.path), tags=("root",))
        self.node_of[iid] = r
        self._insert_children(iid, r)

    def _insert_children(self, parent_iid, node):
        total = node.size or 1
        for i, c in enumerate(node.children[:400]):
            pct = c.size / total * 100
            iid = self.tree.insert(parent_iid, "end", text="▸" if c.children else " ",
                                   values=(c.name, human(c.size), f"{pct:.1f}%",
                                           f"{c.files:,}", c.path))
            self.node_of[iid] = c
            if c.children:
                self.tree.insert(iid, "end", text=" ", values=("", "", "", "", ""))
                self.node_of[self.tree.get_children(iid)[0]] = None
            if pct > 40:
                self.tree.item(iid, tags=("big",))
        self.tree.tag_configure("big", foreground=RED)
        self.tree.tag_configure("root", font=(F_BODY[0], 10, "bold"))

    def _on_open(self, _):
        iid = self.tree.focus()
        node = self.node_of.get(iid)
        if not node or not node.children:
            return
        kids = self.tree.get_children(iid)
        if len(kids) == 1 and self.node_of.get(kids[0]) is None:
            self.tree.delete(kids[0])
            self._insert_children(iid, node)
            self.tree.item(iid, text="▾")

    def _on_dbl(self, _):
        iid = self.tree.focus()
        node = self.node_of.get(iid)
        if node:
            open_in_explorer(node.path)

    def _fill_big(self):
        for i, (sz, p) in enumerate(self.big[:200]):
            self.big_tree.insert("", "end", values=(human(sz), p),
                                 tags=("even",) if i % 2 else ())

    def _open_big(self, _):
        sel = self.big_tree.selection()
        if not sel:
            return
        p = self.big_tree.item(sel[0], "values")[1]
        open_in_explorer(p)

    # ------------------------------------------------------------------ 迁移
    def migrate_node(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在目录树里选择一个目录")
            return
        node = self.node_of.get(sel[0])
        if not node:
            messagebox.showinfo("提示", "请选择一个有效目录")
            return
        self.app.custom_migrate(node.path, node.size)
