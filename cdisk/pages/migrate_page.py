# -*- coding: utf-8 -*-
"""迁移页：扫描可迁移目标 → 勾选 → 一键搬到其他盘 → 建立目录联接。"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..migrate import (build_jobs, find_record_by_src, is_lock_error,
                       migrate_job, rollback)
from ..ui import (ACCENT, BG, BORDER, CARD, GREEN, MUTED, ORANGE, RED, SUB, TEXT,
                  button, card, entry, label, run_async, tree, F_BODY, F_H1, F_SMALL,
                  F_TITLE)
from ..util import human, is_admin
from .unlock import show_unlock

BOX_ON, BOX_OFF = "☑", "☐"

STATE_TXT = {
    "ok": ("可迁移", MUTED),
    "part": ("部分已迁移", ORANGE),
    "done": ("已迁移", GREEN),
    "none": ("未安装", SUB),
    "manual": ("需手动", MUTED),
}

HELP_TEXT = """【1】找到真实缓存目录
Edge 的网页缓存并不在某个可设置的地方，它硬编码在这个路径下：
    C:\\Users\\<你>\\AppData\\Local\\Microsoft\\Edge\\User Data\\Default\\Cache
同级的还有 Code Cache、GPUCache、ShaderCache、
Service Worker\\CacheStorage 等几个目录，工具会把它们一起搬。

【2】复制到目标盘
    D:\\CDiskSaver\\edge_cache\\Default\\Cache
用 robocopy 多线程复制，复制完逐个核对「文件数量」和「总字节数」。

【3】校验（关键的一步）
数量或大小对不上 → 立刻删掉 D 盘副本，C 盘原目录一个字节都不动，
然后告诉你失败原因。只有完全一致才进入下一步。

【4】原目录改名让位
    Cache  →  Cache.__cdisk_bak
只是改名，瞬间完成，不产生额外空间占用。

【5】建立目录联接
    mklink /J "C:\\...\\Default\\Cache" "D:\\CDiskSaver\\edge_cache\\Default\\Cache"
这是 NTFS 的「目录联接（Junction）」，在文件系统层把原路径重定向到 D 盘。
它不是快捷方式，不是软链接，是文件系统级的重定向：
任何程序按原路径打开文件，读写的其实都是 D 盘那份。

【6】删除 .__cdisk_bak
到这一步 C 盘空间才真正被释放。

—— 之后会发生什么 ——
Edge 下次启动，仍然按 C:\\...\\Default\\Cache 去读写，
Windows 在底层把它转到 D 盘，Edge 完全感知不到。
书签、密码、登录状态、历史记录一律不动，因为你只搬了缓存目录。

—— 为什么不直接改 Edge 的设置 ——
Edge 确实有 --disk-cache-dir 启动参数和 DiskCacheDir 策略，
但它们只覆盖一部分缓存，而且软件升级、新建快捷方式后容易失效，
还得改每个用户的快捷方式。目录联接是文件系统层的，
对任何软件通用，不需要软件配合，也不用改注册表。

—— 风险与回退 ——
· 迁移时必须关闭 Edge，否则文件被占用，第【4】步改名会失败
  （工具会提示并自动回退，不会留下半成品）。
· 极少数会检测「重解析点」的软件可能不适应目录联接。
  真遇到问题：「迁移记录」→ 选中 → 还原，数据搬回 C 盘、删掉联接，
  恢复到迁移前的状态。
· 校验和回退这两条是硬保证：任何一步失败，你的数据都在原处。
"""


class MigratePage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.rows = {}
        self.checked = {}
        self.busy = False
        self.cancel = threading.Event()
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        pad = 22
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=pad, pady=(18, 8))
        label(head, "缓存迁移", F_TITLE, TEXT, BG).pack(side="left")
        label(head, "勾选要搬走的缓存目录，原位置会留下目录联接，软件无感知",
              F_SMALL, MUTED, BG).pack(side="left", padx=12)
        button(head, "迁移原理", self.show_help, "ghost").pack(side="right")

        # 第一行：落点设置
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=pad, pady=(0, 6))
        label(bar, "迁移落点", F_SMALL, MUTED, BG).pack(side="left")
        self.var_dest = tk.StringVar(value=self.app.svc.dest_root)
        entry(bar, self.var_dest, width=42).pack(side="left", padx=8, ipady=3)
        button(bar, "浏览", self._pick_dest, "ghost").pack(side="left")
        button(bar, "保存", self._save_dest, "ghost").pack(side="left", padx=6)
        self.var_backup = tk.BooleanVar(value=self.app.svc.keep_backup)
        ttk.Checkbutton(bar, text="迁移后保留 C 盘备份", variable=self.var_backup,
                        command=self._save_dest).pack(side="left", padx=12)

        # 第二行：选择与操作
        bar2 = tk.Frame(self, bg=BG)
        bar2.pack(fill="x", padx=pad, pady=(0, 8))
        self.btn_all = button(bar2, "全选可迁移", self.select_all, "ghost")
        self.btn_all.pack(side="left")
        self.btn_none = button(bar2, "清空勾选", self.select_none, "ghost")
        self.btn_none.pack(side="left", padx=6)
        button(bar2, "迁移指定目录…", self.custom_dialog, "soft").pack(side="left", padx=6)
        self.lbl_sel = label(bar2, "未勾选任何项", F_SMALL, MUTED, BG)
        self.lbl_sel.pack(side="left", padx=10)

        self.btn_refresh = button(bar2, "重新扫描", self.refresh, "ghost")
        self.btn_refresh.pack(side="right")
        self.btn_rollback = button(bar2, "还原选中", self.rollback_selected, "danger")
        self.btn_rollback.pack(side="right", padx=8)
        self.btn_go = button(bar2, "迁移勾选项 (0)", self.migrate_selected)
        self.btn_go.pack(side="right")

        wrap = card(self)
        wrap.pack(fill="both", expand=True, padx=pad, pady=(0, 8))
        cols = [("chk", ""), ("name", "名称"), ("cat", "类别"), ("state", "状态"),
                ("size", "占用"), ("dst", "迁移到")]
        frame, self.tree = tree(wrap.inner, cols, [34, 230, 88, 100, 92, 330],
                                height=14,
                                stretch=[False, True, False, False, False, True])
        frame.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_dbl)

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=pad, pady=(0, 8))
        self.pb = ttk.Progressbar(foot, style="Thin.Horizontal.TProgressbar",
                                  maximum=100, length=240)
        self.pb.pack(side="left")
        self.lbl_status = label(foot, "就绪", F_SMALL, MUTED, BG)
        self.lbl_status.pack(side="left", padx=12)
        self.btn_cancel = button(foot, "取消", self._cancel, "ghost")
        self.btn_cancel.pack(side="right")
        self.btn_cancel.configure(state="disabled")

        self.log = tk.Text(self, height=5, bg="#0f172a", fg="#cbd5e1",
                           font=("Consolas", 9), relief="flat", padx=10, pady=6,
                           insertbackground="#cbd5e1")
        self.log.pack(fill="x", padx=pad, pady=(0, 14))
        self.log.configure(state="disabled")
        self._log("就绪。勾选左侧 ☐ 后点「迁移勾选项」，或双击某一行查看目录。")

    # ------------------------------------------------------------------ 说明
    def show_help(self):
        win = tk.Toplevel(self)
        win.title("迁移原理")
        win.configure(bg=BG)
        win.geometry("820x660")
        win.transient(self.winfo_toplevel())
        top = tk.Frame(win, bg=BG)
        top.pack(fill="x", padx=18, pady=(14, 6))
        label(top, "迁移原理 · 以 Edge 浏览器缓存为例", F_H1, TEXT, BG).pack(side="left")
        button(top, "关闭", win.destroy, "ghost").pack(side="right")

        box = tk.Text(win, wrap="word", bg=CARD, fg=TEXT, font=(F_BODY[0], 10),
                      relief="flat", padx=18, pady=14, spacing1=2, spacing3=4)
        sb = ttk.Scrollbar(win, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 6), pady=(0, 14))
        box.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        box.insert("1.0", HELP_TEXT)
        box.configure(state="disabled")

    # ------------------------------------------------------------------ 基础
    def _pick_dest(self):
        d = filedialog.askdirectory(title="选择迁移落点（建议非 C 盘）")
        if d:
            self.var_dest.set(os.path.join(d, "CDiskSaver"))
            self._save_dest()

    def _save_dest(self):
        self.app.svc.dest_root = self.var_dest.get().strip()
        self.app.svc.keep_backup = self.var_backup.get()
        self.app.svc.save()
        self._log(f"落点已设为 {self.app.svc.dest_root}")

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", f"[{self._ts()}] {msg}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    @staticmethod
    def _ts():
        import time
        return time.strftime("%H:%M:%S")

    def _set_status(self, text):
        self.lbl_status.configure(text=text)

    def _on_dbl(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        r = self.rows.get(sel[0])
        if r and r["dirs"]:
            from ..util import open_in_explorer
            open_in_explorer(r["dirs"][0])

    # ------------------------------------------------------------------ 勾选
    def _on_click(self, event):
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if col == "#1":
            self._toggle(row)
            return "break"
        return None

    def _toggle(self, iid):
        r = self.rows.get(iid)
        if not r:
            return
        if r["state"] not in ("ok", "part"):
            return
        tid = r["t"].id
        self.checked[tid] = not self.checked.get(tid, False)
        self.tree.set(iid, "chk", BOX_ON if self.checked[tid] else BOX_OFF)
        self._update_sel()

    def select_all(self):
        for iid, r in self.rows.items():
            if r["state"] in ("ok", "part"):
                self.checked[r["t"].id] = True
                self.tree.set(iid, "chk", BOX_ON)
        self._update_sel()

    def select_none(self):
        for tid in list(self.checked):
            self.checked[tid] = False
        for iid in self.rows:
            self.tree.set(iid, "chk", BOX_OFF)
        self._update_sel()

    def _update_sel(self):
        picked = self._picked_rows()
        total = sum(r["size"] for r in picked)
        n = len(picked)
        self.lbl_sel.configure(
            text=f"已勾选 {n} 项 · 合计 {human(total)}" if n else "未勾选任何项（点最左侧 ☐）",
            fg=ACCENT if n else MUTED)
        self.btn_go.configure(text=f"迁移勾选项 ({n})")
        # 只有执行中才禁用；没勾选时保持可点，点了会明确提示，而不是静默无反应
        self.btn_go.configure(state="disabled" if self.busy else "normal")

    def _picked_rows(self):
        return [r for r in self.rows.values()
                if self.checked.get(r["t"].id) and r["state"] in ("ok", "part")]

    # ------------------------------------------------------------------ 扫描
    def on_show(self):
        """每次切到本页都要保证表格有内容——不能只在 tinfo 为空时才扫。"""
        if self.app.svc.tinfo:
            if not self.rows:
                self._fill()
                self._set_status(f"共 {len(self.app.svc.tinfo)} 项")
            return
        if self.busy:
            return
        if getattr(self.app, "_scanning", False):
            self._set_status("正在扫描可迁移目录 …")
            return
        self.refresh()

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self._set_status("正在扫描 …")
        self.btn_go.configure(state="disabled")
        self.pb.configure(mode="indeterminate")
        self.pb.start(12)

        def work():
            return self.app.svc.scan_targets(progress=self._stage)

        def done(_):
            self.busy = False
            self.pb.stop()
            self.pb.configure(mode="determinate", value=0)
            self._fill()
            self._set_status(f"扫描完成，共 {len(self.app.svc.tinfo)} 项")
            self.app.on_targets_updated()

        def fail(exc):
            self.busy = False
            self.pb.stop()
            self.pb.configure(mode="determinate", value=0)
            self._set_status(f"扫描失败：{exc}")
            self._update_sel()

        run_async(self.app.post, work, done, on_error=fail)

    def _stage(self, msg):
        self.app.post(lambda: self._set_status(msg))

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        order = {"ok": 0, "part": 1, "done": 2, "manual": 3, "none": 4}
        rows = sorted(self.app.svc.tinfo, key=lambda r: (order.get(r["state"], 9), -r["size"]))
        for i, r in enumerate(rows):
            t = r["t"]
            txt, _ = STATE_TXT.get(r["state"], ("?", MUTED))
            can = r["state"] in ("ok", "part")
            on = bool(self.checked.get(t.id)) and can
            self.checked[t.id] = on
            tags = ["even"] if i % 2 else []
            if r["state"] == "done":
                tags.append("done")
            elif r["state"] == "part":
                tags.append("warn")
            elif r["state"] in ("none", "manual"):
                tags.append("muted")
            iid = self.tree.insert("", "end", values=(
                BOX_ON if on else BOX_OFF, t.name, t.cat, txt,
                human(r["size"]) if r["size"] else "-",
                r["dst"] or ("—" if r["state"] != "manual" else "点「迁移原理」查看"),
            ), tags=tuple(tags))
            self.rows[iid] = r
        self.tree.tag_configure("done", foreground=GREEN)
        self.tree.tag_configure("warn", foreground=ORANGE)
        self.tree.tag_configure("muted", foreground=SUB)
        self._update_sel()

    # ------------------------------------------------------------------ 指定目录
    def custom_dialog(self):
        """直接输入/粘贴一个目录路径来迁移，不必先去空间分析里扫描。"""
        win = tk.Toplevel(self)
        win.title("迁移指定目录")
        win.configure(bg=BG)
        win.geometry("700x330")
        win.transient(self.winfo_toplevel())
        win.grab_set()

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        label(body, "把任意目录搬到其他盘", F_H1, TEXT, BG).pack(anchor="w")
        label(body, "原路径会变成一个指向新位置的目录联接，程序照常访问，感知不到",
              F_SMALL, MUTED, BG).pack(anchor="w", pady=(2, 14))

        var = tk.StringVar()
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x")
        entry(row, var, width=54).pack(side="left", ipady=3)
        button(row, "浏览", lambda: self._pick_custom(var), "ghost").pack(side="left", padx=6)
        button(row, "检测", lambda: self._probe_custom(var), "ghost").pack(side="left")

        self.lbl_custom = label(body, "填入路径后点「检测」查看体积", F_SMALL, MUTED, BG)
        self.lbl_custom.pack(anchor="w", pady=(10, 0))

        tip = ("迁移前请确认：\n"
               "· 相关程序已完全关闭，否则文件被占用会导致迁移失败（不会损坏数据）\n"
               "· 不要迁移程序自身的安装目录（如 Program Files 下的文件夹）\n"
               "· 迁移后随时可在「迁移记录」里一键还原")
        label(body, tip, F_SMALL, ORANGE, BG, justify="left").pack(anchor="w", pady=(12, 0))

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=20, pady=(0, 16))

        def go():
            p = var.get().strip().strip('"').strip("'")
            if not p or not os.path.isdir(p):
                messagebox.showerror("路径无效", "请填入一个存在的目录路径", parent=win)
                return
            win.destroy()
            self.app.custom_migrate(p)

        button(btns, "开始迁移", go).pack(side="right")
        button(btns, "取消", win.destroy, "ghost").pack(side="right", padx=8)
        return win

    def _pick_custom(self, var):
        d = filedialog.askdirectory(title="选择要迁移的目录", parent=self)
        if d:
            var.set(os.path.normpath(d))
            self._probe_custom(var)

    def _set_custom_label(self, text, fg=MUTED):
        try:
            if self.lbl_custom.winfo_exists():
                self.lbl_custom.configure(text=text, fg=fg)
        except Exception:
            pass

    def _probe_custom(self, var):
        p = var.get().strip().strip('"').strip("'")
        if not p or not os.path.isdir(p):
            self._set_custom_label("路径不存在", RED)
            return
        self._set_custom_label("正在统计体积 …", MUTED)

        def work():
            from ..util import dir_stats
            return dir_stats(p)

        def done(res):
            files, size = res
            from ..util import drive_of
            self._set_custom_label(
                f"{human(size)} · {files:,} 个文件 · 位于 {drive_of(p)}",
                ACCENT if size else MUTED)

        run_async(self.app.post, work, done)

    # ------------------------------------------------------------------ 迁移
    def quick_one(self, row):
        """概览页点「迁移」时调用。"""
        self.migrate_targets([row["t"]])

    def migrate_selected(self):
        picked = self._picked_rows()
        if not picked:
            # 兜底：没有勾选时，用表格里高亮选中的行
            sel = [self.rows[i] for i in self.tree.selection() if i in self.rows]
            picked = [r for r in sel if r["state"] in ("ok", "part")]
        if not picked:
            messagebox.showinfo(
                "还没有选择项目",
                "两种选择方式，任选其一：\n\n"
                "1. 点击列表最左侧的 ☐，勾选要迁移的项目\n"
                "2. 点一行把它高亮选中，再点「迁移勾选项」\n\n"
                "想一次性全选，直接点左边的「全选可迁移」。")
            return
        self.migrate_targets([r["t"] for r in picked])

    def migrate_targets(self, targets, quiet=False):
        """quiet=True 表示这是「关闭占用」后的自动重试，不再弹一次确认框。"""
        if self.busy:
            messagebox.showinfo("提示", "当前有任务在执行")
            return

        dest = self.var_dest.get().strip()
        if not dest:
            messagebox.showerror("错误", "请先设置迁移落点")
            return
        dest_drive = os.path.splitdrive(os.path.abspath(dest))[0].upper()
        home_drive = os.path.splitdrive(os.environ.get("USERPROFILE") or "C:\\")[0].upper()
        if dest_drive and dest_drive == home_drive:
            if not messagebox.askyesno("目标盘与 C 盘相同",
                                       "迁移落点位于 C 盘，无法释放空间。仍要继续吗？"):
                return
        self._save_dest()

        if not quiet:
            names = "、".join(t.name for t in targets[:8]) + ("…" if len(targets) > 8 else "")
            tip = "" if is_admin() else "\n（当前为普通权限，位于 ProgramData / Windows 下的目录可能失败）"
            if not messagebox.askyesno(
                    "确认迁移",
                    f"即将迁移 {len(targets)} 项：\n{names}\n\n"
                    f"落点：{dest}\n\n"
                    "流程：复制 → 校验 → 建立目录联接 → 释放 C 盘原件。\n"
                    "过程中请关闭对应软件，避免文件被占用。" + tip):
                return

        self.busy = True
        self.cancel.clear()
        self.btn_go.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")
        self.btn_all.configure(state="disabled")
        self.btn_none.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.pb.configure(mode="determinate", value=0)

        def stage(msg):
            self.app.post(lambda: self._set_status(msg))

        def prog(p):
            self.app.post(lambda: self.pb.configure(value=max(0, min(100, p * 100))))

        def work():
            ok_cnt, fail_cnt, freed = 0, 0, 0
            locked = []
            total = len(targets)
            for idx, t in enumerate(targets, 1):
                if self.cancel.is_set():
                    self.app.post(lambda: self._log("已取消剩余任务"))
                    break
                self.app.post(lambda t=t, i=idx, n=total:
                              self._log(f"({i}/{n}) 开始处理：{t.name}"))
                jobs = build_jobs(t, dest)
                if not jobs:
                    self.app.post(lambda t=t: self._log(f"  {t.name}：目录不存在，跳过"))
                    continue
                for j in jobs:
                    if self.cancel.is_set():
                        break
                    j.scan()
                    self.app.post(lambda j=j: self._log(
                        f"  {j.src}  ({human(j.bytes)}, {j.files} 个文件)"))
                    ok, msg, rec = migrate_job(
                        j, progress=prog, stage=stage, cancel=self.cancel,
                        keep_backup=self.var_backup.get())
                    if ok:
                        ok_cnt += 1
                        freed += j.bytes
                        self.app.post(lambda m=msg: self._log(f"  ✔ {m}"))
                    else:
                        fail_cnt += 1
                        if is_lock_error(msg):
                            locked.append(t)
                        self.app.post(lambda m=msg: self._log(f"  ✘ {m}"))
            return ok_cnt, fail_cnt, freed, locked

        def done(res):
            ok_cnt, fail_cnt, freed, locked = res
            self.busy = False
            self.btn_refresh.configure(state="normal")
            self.btn_all.configure(state="normal")
            self.btn_none.configure(state="normal")
            self.btn_cancel.configure(state="disabled")
            self.pb.configure(value=100 if ok_cnt else 0)
            self._set_status(f"完成：成功 {ok_cnt}，失败 {fail_cnt}，释放 {human(freed)}")
            self._log(f"===== 结束：成功 {ok_cnt} / 失败 {fail_cnt}，释放 {human(freed)} =====")
            for t in targets:
                self.checked[t.id] = False
            self.refresh()
            self.app.on_targets_updated()

        if locked:
            self.after(400, lambda: self._offer_unlock(locked))
        elif ok_cnt:
            # 成功也要给个明确反馈，否则用户不知道到底成没成
            freed_txt = human(freed)
            self._log(f"===== 全部成功：{ok_cnt} 项，释放 {freed_txt} =====")
            messagebox.showinfo(
                "迁移完成",
                f"成功迁移 {ok_cnt} 项，C 盘释放约 {freed_txt}。\n\n"
                "原路径已变成指向新位置的目录联接，程序照常使用。\n"
                "随时可在「迁移记录」里一键还原。")

        run_async(self.app.post, work, done,
                  on_error=lambda e: (self._log(f"异常：{e}"), self._reset()))

    def _offer_unlock(self, targets):
        """迁移因占用失败时，提供一键关闭占用程序并重试。"""
        names = "、".join(t.name for t in targets[:5])
        if not messagebox.askyesno(
                "有程序正在占用文件",
                f"以下 {len(targets)} 项因为文件被占用而没能迁移：\n{names}\n\n"
                "要不要查找并关闭占用这些目录的程序？\n"
                "（关闭前请先保存工作，未保存的数据会丢失）"):
            self._log("已跳过「关闭占用程序」，迁移未完成")
            self._set_status("迁移未完成：文件被占用，可稍后关闭相关程序再试")
            return
        paths = []
        for t in targets:
            paths.extend(t.expand())
        show_unlock(self, self.app, paths,
                    on_retry=lambda note="": self._retry_when_idle(targets, 0, note))

    def _retry_when_idle(self, targets, tries=0, note=""):
        """等扫描/刷新结束再重试，避免撞上 busy 直接退出。"""
        if note:
            self._log(note)
            self._set_status(f"{note}，正在准备重试 …")
        if self.busy and tries < 60:
            self.after(500, lambda: self._retry_when_idle(targets, tries + 1, ""))
            return
        if self.busy:
            self._log("===== 重试中止：后台任务一直没结束 =====")
            self._set_status("重试中止：后台任务未结束，请稍后手动点「迁移勾选项」")
            messagebox.showwarning(
                "暂时无法重试",
                "后台还有一个任务没结束（扫描或迁移中），等它完成后请手动点"
                "「迁移勾选项」再试一次。")
            return
        self.migrate_targets(targets, quiet=bool(note))

    def _reset(self):
        self.busy = False
        self.btn_refresh.configure(state="normal")
        self.btn_all.configure(state="normal")
        self.btn_none.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        self._update_sel()

    def _cancel(self):
        self.cancel.set()
        self._log("正在取消 …（当前文件复制完成后停止）")

    # ------------------------------------------------------------------ 还原
    def rollback_selected(self):
        sel = self.tree.selection()
        picked = self._picked_rows()
        rows = [self.rows[i] for i in sel if i in self.rows] or picked
        recs = []
        for r in rows:
            if r["state"] not in ("done", "part"):
                continue
            for d in r["dirs"]:
                rec = find_record_by_src(d)
                if rec and rec.get("status") == "done":
                    recs.append(rec)
        if not recs:
            messagebox.showinfo("提示", "请先选中已迁移的项目（状态为「已迁移」）")
            return
        if not messagebox.askyesno("确认还原",
                                   f"将把 {len(recs)} 个目录搬回 C 盘并删除联接。\n"
                                   "请确认 C 盘有足够空间。"):
            return
        self.busy = True
        self.btn_go.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")

        def stage(msg):
            self.app.post(lambda: self._set_status(msg))

        def prog(p):
            self.app.post(lambda: self.pb.configure(value=p * 100))

        def work():
            ok = 0
            for rec in recs:
                self.app.post(lambda r=rec: self._log(f"还原：{r['src']}"))
                good, msg = rollback(rec, progress=prog, stage=stage)
                ok += 1 if good else 0
                self.app.post(lambda g=good, m=msg: self._log(("  ✔ " if g else "  ✘ ") + m))
            return ok

        def done(ok):
            self.busy = False
            self.btn_refresh.configure(state="normal")
            self._set_status(f"还原完成 {ok}/{len(recs)}")
            self.refresh()
            self.app.on_targets_updated()

        run_async(self.app.post, work, done,
                  on_error=lambda e: (self._log(f"异常：{e}"), self._reset()))
