# -*- coding: utf-8 -*-
"""清理页：系统垃圾一键清理。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..clean import ITEMS
from ..ui import (ACCENT, BG, CARD, GREEN, MUTED, ORANGE, RED, SUB, TEXT, button,
                  card, label, run_async, tree, F_BODY, F_H1, F_SMALL, F_TITLE)
from ..util import human, is_admin, relaunch_as_admin

DANGER = {"safe": ("安全", GREEN), "caution": ("谨慎", ORANGE), "high": ("高风险", RED)}
BOX_ON, BOX_OFF = "☑", "☐"


class CleanPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.checked = {}
        self.sizes = {}
        self.rows = {}
        self.busy = False
        self._build()

    def _build(self):
        pad = 22
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=pad, pady=(18, 8))
        label(head, "系统清理", F_TITLE, TEXT, BG).pack(side="left")
        label(head, "只清理可以重建的缓存与临时文件，不会动你的个人数据",
              F_SMALL, MUTED, BG).pack(side="left", padx=12)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=pad, pady=(0, 8))
        self.btn_scan = button(bar, "重新统计", self.scan_sizes, "ghost")
        self.btn_scan.pack(side="left")
        self.btn_all = button(bar, "全选安全项", self.select_safe, "ghost")
        self.btn_all.pack(side="left", padx=8)
        self.btn_run = button(bar, "开始清理", self.run_clean)
        self.btn_run.pack(side="right")
        self.lbl_total = label(bar, "合计 0 B", F_H1, ACCENT, BG)
        self.lbl_total.pack(side="right", padx=14)

        c = card(self, padx=0, pady=0)
        c.pack(fill="both", expand=True, padx=pad, pady=(0, 10))
        cols = [("chk", ""), ("name", "项目"), ("desc", "说明"),
                ("size", "可释放"), ("risk", "风险")]
        frame, self.tree = tree(c.inner, cols, [34, 220, 480, 100, 80], height=14,
                                stretch=[False, False, True, False, False])
        frame.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self._on_click)
        for i, it in enumerate(ITEMS):
            txt, color = DANGER.get(it.danger, ("?", MUTED))
            iid = self.tree.insert("", "end", values=(
                BOX_OFF, it.name, it.desc, "…", txt),
                tags=(("even",) if i % 2 else ()) + (("bad",) if it.danger == "high" else ()))
            self.rows[iid] = it
            self.checked[iid] = False

        self.log = tk.Text(self, height=6, bg="#0f172a", fg="#cbd5e1",
                           font=("Consolas", 9), relief="flat", padx=10, pady=6)
        self.log.pack(fill="x", padx=pad, pady=(0, 14))
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------ 交互
    def _on_click(self, event):
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or col != "#1":
            return
        self.checked[row] = not self.checked.get(row, False)
        self.tree.set(row, "chk", BOX_ON if self.checked[row] else BOX_OFF)
        self._update_total()

    def _update_total(self):
        total = sum(self.sizes.get(iid, 0) for iid, on in self.checked.items() if on)
        n = sum(1 for on in self.checked.values() if on)
        self.lbl_total.configure(text=f"已选 {n} 项 · 合计 {human(total)}")

    def select_safe(self):
        for iid, it in self.rows.items():
            on = it.danger == "safe"
            self.checked[iid] = on
            self.tree.set(iid, "chk", BOX_ON if on else BOX_OFF)
        self._update_total()

    def _log(self, msg):
        import time
        self.log.configure(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------ 统计
    def on_show(self):
        if not self.sizes:
            self.scan_sizes()

    def scan_sizes(self):
        if self.busy:
            return
        self.busy = True
        self.btn_scan.configure(state="disabled")
        for iid in self.rows:
            self.tree.set(iid, "size", "…")

        def work():
            out = {}
            for iid, it in list(self.rows.items()):
                try:
                    out[iid] = it.size()
                except Exception:
                    out[iid] = 0
            return out

        def done(out):
            self.sizes = out
            for iid, sz in out.items():
                it = self.rows[iid]
                self.tree.set(iid, "size", human(sz) if sz else "—")
            self.busy = False
            self.btn_scan.configure(state="normal")
            self._update_total()
            self._log(f"统计完成，共可释放 {human(sum(out.values()))}")

        run_async(self.app.post, work, done,
                  on_error=lambda e: (self.busy, self.btn_scan.configure(state="normal")))

    # ------------------------------------------------------------------ 清理
    def run_clean(self):
        if self.busy:
            return
        sel = [(iid, it) for iid, it in self.rows.items() if self.checked.get(iid)]
        if not sel:
            messagebox.showinfo("提示", "请先勾选要清理的项目")
            return
        need_admin = any(it.admin for _, it in sel)
        if need_admin and not is_admin():
            if messagebox.askyesno("需要管理员权限",
                                   "选中项包含需要管理员权限的系统目录。\n是否以管理员身份重启？"):
                if relaunch_as_admin():
                    self.app.root.destroy()
            return
        danger = [it.name for _, it in sel if it.danger == "high"]
        msg = f"即将清理 {len(sel)} 项，预计释放 {human(sum(self.sizes.get(i,0) for i,_ in sel))}。"
        if danger:
            msg += "\n\n包含高风险项：\n· " + "\n· ".join(danger) + "\n\n确定继续？"
        if not messagebox.askyesno("确认清理", msg):
            return

        self.busy = True
        self.btn_run.configure(state="disabled")
        self.btn_scan.configure(state="disabled")

        def work():
            freed = 0
            for iid, it in sel:
                self.app.post(lambda n=it.name: self._log(f"清理：{n}"))
                before = self.sizes.get(iid, 0)
                try:
                    ok, msg2 = it.run(log=lambda m: self.app.post(lambda m=m: self._log("  " + m)))
                except Exception as exc:  # noqa: BLE001
                    ok, msg2 = False, str(exc)
                self.app.post(lambda ok=ok, m=msg2: self._log(("  ✔ " if ok else "  ✘ ") + m))
                if ok:
                    freed += before
            return freed

        def done(freed):
            self.busy = False
            self.btn_run.configure(state="normal")
            self.btn_scan.configure(state="normal")
            self._log(f"===== 清理结束，约释放 {human(freed)} =====")
            self.sizes = {}
            self.scan_sizes()
            self.app.on_targets_updated()

        run_async(self.app.post, work, done,
                  on_error=lambda e: (self.busy, self.btn_run.configure(state="normal"),
                                      self.btn_scan.configure(state="normal"),
                                      self._log(f"异常：{e}")))
