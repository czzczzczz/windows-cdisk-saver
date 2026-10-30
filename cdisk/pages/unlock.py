# -*- coding: utf-8 -*-
"""「关闭占用程序」对话框：找出占用目录的进程，勾选后一键结束并重试迁移。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..handles import is_protected, kill_processes, using_processes
from ..ui import (ACCENT, BG, BORDER, CARD, GREEN, MUTED, ORANGE, RED, SUB, TEXT,
                  button, card, label, run_async, tree, F_BODY, F_H1, F_SMALL, F_TITLE)

BOX_ON, BOX_OFF = "☑", "☐"


def show_unlock(parent, app, paths, on_retry=None):
    """弹窗列出占用进程。paths 可以是目录列表。"""
    paths = [p for p in (paths or []) if p]
    win = tk.Toplevel(parent)
    win.title("关闭占用程序")
    win.configure(bg=BG)
    win.geometry("760x520")
    win.transient(parent.winfo_toplevel())
    win.grab_set()

    pad = 20
    head = tk.Frame(win, bg=BG)
    head.pack(fill="x", padx=pad, pady=(16, 4))
    label(head, "这些程序占用了要迁移的目录", F_H1, TEXT, BG).pack(side="left")

    sub = tk.Frame(win, bg=BG)
    sub.pack(fill="x", padx=pad)
    shown = paths[0] if len(paths) == 1 else f"{len(paths)} 个目录"
    label(sub, shown, F_SMALL, SUB, BG).pack(anchor="w")

    body = card(win, padx=0, pady=0)
    body.pack(fill="both", expand=True, padx=pad, pady=(10, 8))
    cols = [("chk", ""), ("name", "程序"), ("pid", "PID"),
            ("type", "类型"), ("exe", "路径")]
    frame, tv = tree(body.inner, cols, [34, 180, 70, 80, 380], height=10,
                     stretch=[False, False, False, False, True])
    frame.pack(fill="both", expand=True)

    status = label(win, "正在查找占用程序 …", F_SMALL, MUTED, BG)
    status.pack(anchor="w", padx=pad)

    btns = tk.Frame(win, bg=BG)
    btns.pack(fill="x", padx=pad, pady=(6, 16))

    state = {"procs": [], "checked": {}, "rows": {}}

    def refresh_total():
        n = sum(1 for v in state["checked"].values() if v)
        btn_kill.configure(text=f"结束选中并重试 ({n})")

    def toggle(iid):
        p = state["rows"].get(iid)
        if not p or is_protected(p["name"]):
            return
        state["checked"][iid] = not state["checked"].get(iid, False)
        tv.set(iid, "chk", BOX_ON if state["checked"][iid] else BOX_OFF)
        refresh_total()

    def on_click(e):
        iid = tv.identify_row(e.y)
        if iid and tv.identify_column(e.x) == "#1":
            toggle(iid)
            return "break"

    tv.bind("<Button-1>", on_click)

    def fill(procs):
        state["procs"] = procs
        tv.delete(*tv.get_children())
        state["rows"].clear()
        state["checked"].clear()
        if not procs:
            status.configure(
                text="没有找到占用进程。可能是系统缓存占用，或需要管理员权限；"
                     "也可能程序刚退出，直接点「只重试」即可。", fg=ORANGE)
            return
        for i, p in enumerate(procs):
            prot = is_protected(p["name"])
            iid = tv.insert("", "end", values=(
                BOX_OFF if prot else BOX_ON, p["name"], p["pid"],
                p["type"], p["exe"] or p["app"] or "—"),
                tags=("warn",) if prot else (("even",) if i % 2 else ()))
            state["rows"][iid] = p
            state["checked"][iid] = not prot
        tv.tag_configure("warn", foreground=RED)
        n = sum(1 for v in state["checked"].values() if v)
        status.configure(text=f"找到 {len(procs)} 个占用进程，已勾选 {n} 个。"
                              f"受保护的系统进程已置灰、无法勾选。", fg=MUTED)
        refresh_total()

    def work():
        seen, out = set(), []
        for p in paths:
            for proc in using_processes(p):
                if proc["pid"] in seen:
                    continue
                seen.add(proc["pid"])
                out.append(proc)
        return out

    def do_kill():
        pids = [state["rows"][i]["pid"] for i, v in state["checked"].items()
                if v and i in state["rows"]]
        if not pids:
            messagebox.showinfo("提示", "没有勾选任何进程", parent=win)
            return
        names = "、".join(sorted({state["rows"][i]["name"]
                                 for i, v in state["checked"].items()
                                 if v and i in state["rows"]}))
        if not messagebox.askyesno(
                "确认结束进程",
                f"即将强制结束 {len(pids)} 个进程：\n{names}\n\n"
                "未保存的数据会丢失。确定继续？", parent=win):
            return
        btn_kill.configure(state="disabled")
        status.configure(text="正在结束进程 …", fg=MUTED)
        ok, bad = kill_processes(pids)
        win.after(1200, lambda: finish(ok, bad))

    def finish(ok, bad):
        win.grab_release()
        win.destroy()
        if bad:
            messagebox.showwarning(
                "部分进程未能结束",
                f"成功 {ok} 个，失败 {len(bad)} 个。\n"
                "失败通常是权限不足（需要管理员）或进程受系统保护。")
        if on_retry:
            on_retry()

    def do_retry():
        win.grab_release()
        win.destroy()
        if on_retry:
            on_retry()

    btn_kill = button(btns, "结束选中并重试 (0)", do_kill)
    btn_kill.pack(side="right")
    button(btns, "只重试", do_retry, "soft").pack(side="right", padx=8)
    button(btns, "取消", lambda: (win.grab_release(), win.destroy()), "ghost").pack(
        side="right")

    run_async(app.post, work, fill,
              on_error=lambda e: status.configure(text=f"查找失败：{e}", fg=RED))
    return win
