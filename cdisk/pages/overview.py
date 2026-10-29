# -*- coding: utf-8 -*-
"""概览页：C 盘体检 + 一键建议。"""
from __future__ import annotations

import os
import tkinter as tk

from ..ui import (ACCENT, ACCENT_BG, BG, BORDER, CARD, GREEN, MUTED, ORANGE, RED,
                  SUB, TEXT, Bar, button, card, label, run_async, status_pill, F_BODY,
                  F_H1, F_SMALL, F_TITLE)
from ..util import free_bytes, human, is_admin


class OverviewPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        pad = 22
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=pad, pady=(18, 10))
        label(head, "C 盘体检", F_TITLE, TEXT, BG).pack(side="left")
        self.lbl_admin = status_pill(head, "", ORANGE, "#fff7ed")
        self.lbl_admin.pack(side="left", padx=12)
        button(head, "重新体检", lambda: self.app.refresh_targets(), "ghost").pack(side="right")
        self.btn_mig = button(head, "去迁移", lambda: self.app.open_page("migrate"))
        self.btn_mig.pack(side="right", padx=8)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=pad, pady=(0, 16))

        # C 盘主卡片
        c1 = card(body)
        c1.pack(fill="x")
        inner = c1.inner
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x")
        left = tk.Frame(row, bg=CARD)
        left.pack(side="left", anchor="w")
        label(left, "C 盘可用空间", F_SMALL, MUTED).pack(anchor="w")
        self.lbl_free = label(left, "—", (F_TITLE[0], 30, "bold"), TEXT)
        self.lbl_free.pack(anchor="w", pady=(2, 0))
        self.lbl_total = label(left, "", F_SMALL, SUB)
        self.lbl_total.pack(anchor="w")

        right = tk.Frame(row, bg=CARD)
        right.pack(side="right", anchor="e")
        self.lbl_state = label(right, "", F_H1, TEXT)
        self.lbl_state.pack(anchor="e")

        self.bar = Bar(inner, height=12)
        self.bar.pack(fill="x", pady=(14, 6))

        self.lbl_hint = label(inner, "", F_SMALL, MUTED)
        self.lbl_hint.pack(anchor="w")

        # 三个统计卡
        stats = tk.Frame(body, bg=BG)
        stats.pack(fill="x", pady=14)
        self.card_mig = self._stat(stats, "可迁移空间", "—", ACCENT, "把缓存搬去其他盘，立即可释放")
        self.card_clean = self._stat(stats, "可清理垃圾", "—", ORANGE, "临时文件、更新缓存、回收站")
        self.card_done = self._stat(stats, "已迁移释放", "—", GREEN, "通过本工具搬离 C 盘的数据")
        for i, c in enumerate((self.card_mig, self.card_clean, self.card_done)):
            c.pack(side="left", fill="both", expand=True, padx=(0 if i == 0 else 10, 0))

        # 建议
        sug = card(body)
        sug.pack(fill="both", expand=True)
        top = tk.Frame(sug.inner, bg=CARD)
        top.pack(fill="x")
        label(top, "迁移建议", F_H1, TEXT).pack(side="left")
        label(top, "按占用从大到小排序，点击右侧按钮直接迁移", F_SMALL, MUTED).pack(side="left", padx=10)

        from ..ui import ScrollFrame
        sf = ScrollFrame(sug.inner, bg=CARD)
        sf.pack(fill="both", expand=True, pady=(8, 0))
        self.sug_body = sf.body

    def _stat(self, parent, title, value, color, desc):
        c = card(parent, padx=16, pady=12)
        label(c.inner, title, F_SMALL, MUTED).pack(anchor="w")
        lbl = label(c.inner, value, (F_TITLE[0], 20, "bold"), color)
        lbl.pack(anchor="w", pady=(2, 2))
        label(c.inner, desc, F_SMALL, SUB, wraplength=210, justify="left").pack(anchor="w")
        c.value = lbl  # type: ignore[attr-defined]
        return c

    # ------------------------------------------------------------------ 数据
    def on_show(self):
        self.refresh()

    def refresh(self):
        u = os.path.splitdrive(os.environ.get("SystemDrive", "C:") + "\\")[0]
        drive = (u or "C:") + "\\"
        free = free_bytes(drive)
        try:
            import shutil
            du = shutil.disk_usage(drive)
            total, used = du.total, du.used
        except Exception:
            total, used = 0, 0
        self.lbl_free.configure(text=human(free))
        self.lbl_total.configure(text=f"总容量 {human(total)} · 已用 {human(used)}")
        ratio = (used / total) if total else 0
        color = RED if ratio > 0.92 else (ORANGE if ratio > 0.8 else ACCENT)
        self.bar.set(ratio, color)
        if ratio > 0.95:
            state, sc = "告急", RED
        elif ratio > 0.88:
            state, sc = "紧张", ORANGE
        elif ratio > 0.75:
            state, sc = "偏高", "#ca8a04"
        else:
            state, sc = "健康", GREEN
        self.lbl_state.configure(text=f"状态：{state}  已用 {ratio*100:.1f}%", fg=sc)

        if is_admin():
            self.lbl_admin.configure(text="管理员模式", fg=GREEN, bg="#f0fdf4")
        else:
            self.lbl_admin.configure(text="普通权限（迁移需要管理员）", fg=ORANGE, bg="#fff7ed")

        tinfo = self.app.svc.tinfo
        if not tinfo:
            self.lbl_hint.configure(text="正在扫描可迁移目标 …")
        else:
            disc = self.app.svc.discovered
            mig = self.app.svc.migratable_bytes() + self.app.svc.discovered_bytes()
            self.card_mig.value.configure(text=human(mig))
            self.card_done.value.configure(text=human(self.app.svc.moved_bytes()))
            n_builtin = sum(1 for r in tinfo if r["state"] in ("ok", "part") and r["size"] > 0)
            extra = f"、未收录大目录 {len(disc)} 个" if disc else ""
            tail = "（正在发现未收录的大目录 …）" if self.app.svc.discovering else ""
            self.lbl_hint.configure(
                text=f"共发现内置目标 {n_builtin} 个{extra}，全部迁移预计释放 {human(mig)}。{tail}")
            self._render_suggestions(tinfo, disc)

        # 垃圾大小异步统计
        run_async(self.app.post, self._calc_garbage, self._on_garbage)

    def _calc_garbage(self):
        from ..clean import ITEMS
        total = 0
        for it in ITEMS:
            if it.danger == "high" or it.slow:
                continue
            try:
                total += it.size()
            except Exception:
                pass
        return total

    def _on_garbage(self, total):
        self.card_clean.value.configure(text=human(total))

    def _render_suggestions(self, tinfo, disc=None):
        for w in self.sug_body.winfo_children():
            w.destroy()

        rows = [r for r in tinfo if r["state"] in ("ok", "part") and r["size"] > 30 * 1024 * 1024]
        rows.sort(key=lambda r: r["size"], reverse=True)
        disc = disc or []

        if not rows and not disc:
            label(self.sug_body,
                  "没有发现明显可迁移的大目录。可以到「空间分析」里手动找找看。",
                  F_BODY, MUTED).pack(anchor="w", pady=8)
            return

        idx = 0
        for r in rows[:8]:
            self._sug_row(idx, r["t"].name, r["t"].cat, r["size"],
                          ("安全", GREEN, "#f0fdf4") if r["t"].risk == "safe"
                          else ("需关程序", ORANGE, "#fff7ed"),
                          lambda rr=r: self.app.quick_migrate(rr))
            idx += 1

        if disc:
            sep = tk.Frame(self.sug_body, bg=CARD)
            sep.pack(fill="x", pady=(10, 4))
            tk.Frame(sep, bg=BORDER, height=1).pack(fill="x", pady=(0, 6))
            total = human(sum(x["size"] for x in disc))
            label(sep, f"未收录的大目录 · 工具自动发现 {len(disc)} 个，合计 {total}",
                  F_SMALL, ORANGE).pack(anchor="w")
            for r in disc[:8]:
                name = os.path.basename(r["path"].rstrip("\\"))
                parent = os.path.dirname(r["path"])
                short = parent.replace(os.environ.get("USERPROFILE", ""), "~")
                tag = ("安全", GREEN, "#f0fdf4") if r.get("risk") == "safe" \
                    else ("需关程序", ORANGE, "#fff7ed")
                self._sug_row(idx, name, short, r["size"], tag,
                              lambda rr=r: self.app.custom_migrate(rr["path"]))
                idx += 1

    def _sug_row(self, i, name, sub, size, tag, on_click):
        line = tk.Frame(self.sug_body, bg=CARD)
        line.pack(fill="x", pady=1)
        if i % 2 == 0:
            line.configure(bg="#fafbfd")
        bg = line["bg"]
        nm = tk.Frame(line, bg=bg)
        nm.pack(side="left", fill="x", expand=True, pady=6, padx=6)
        label(nm, name, F_BODY, TEXT, bg).pack(side="left")
        label(nm, sub, F_SMALL, SUB, bg).pack(side="left", padx=8)
        p = tk.Label(nm, text=tag[0], font=F_SMALL, fg=tag[1], bg=tag[2], padx=6)
        p.pack(side="left")
        label(line, human(size), F_H1, ACCENT, bg).pack(side="right", padx=14)
        button(line, "迁移", on_click, "soft").pack(side="right", padx=6, pady=4)
