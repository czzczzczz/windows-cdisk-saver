# -*- coding: utf-8 -*-
"""「关闭占用程序」对话框：找出占用目录的进程，勾选后一键结束并重试迁移。

三条硬规矩（都是被真实 bug 逼出来的）：
  1. 每个分支都必须有可见反馈 —— 成功也要说成功，不能静默关窗；
  2. 结束进程不能卡住界面 —— taskkill 可能耗时数秒，必须后台执行；
  3. 判断「杀掉后重不重试」看的是「占用还在不在」，不是文件名 ——
     父进程连同子进程一起被杀、进程其实是临时退出缓存、路径大小写不一致，
     任何一种都会让「按文件名比对」误判成「又被启动了」。
"""
from __future__ import annotations

import os
import threading
import time
import tkinter as tk

from ..handles import is_protected, kill_processes, using_processes
from ..ui import (ACCENT, BG, BORDER, CARD, GREEN, MUTED, ORANGE, RED, SUB, TEXT,
                  button, card, label, run_async, tree, F_BODY, F_H1, F_SMALL, F_TITLE)

BOX_ON, BOX_OFF = "☑", "☐"
NOTE_RETRY = "已跳过结束进程，直接重试迁移"
NOTE_KILLED = "已结束占用进程，重新开始迁移"


def show_unlock(parent, app, paths, on_retry=None):
    """弹窗列出占用进程。paths 可以是目录列表。"""
    paths = [p for p in (paths or []) if p]
    win = tk.Toplevel(parent)
    win.title("关闭占用程序")
    win.configure(bg=BG)
    win.geometry("780x540")
    win.minsize(660, 420)
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
            ("parent", "谁拉起来的"), ("mem", "内存"), ("exe", "路径")]
    frame, tv = tree(body.inner, cols, [34, 160, 62, 180, 68, 300], height=10,
                     stretch=[False, False, False, False, False, True])
    frame.pack(fill="both", expand=True)

    tip = label(win, "「谁拉起来的」从右往左看：关掉最右边那个程序，它就不会再被重启。"
                     "这些都是无窗口的后台进程，任务管理器需在「详细信息」里按 PID 查找。",
                F_SMALL, SUB, BG, justify="left", wraplength=720)
    tip.pack(anchor="w", padx=pad, pady=(0, 2))

    status = label(win, "正在查找占用程序 …", F_SMALL, MUTED, BG)
    status.pack(anchor="w", padx=pad)

    btns = tk.Frame(win, bg=BG)
    btns.pack(fill="x", padx=pad, pady=(6, 16))

    state = {"rows": {}, "checked": {}, "busy": False, "closed": False,
             "killed_names": "", "killed_exes": set()}

    def _dbg_fill(items):
        """给冒烟测试用：不经过 Restart Manager，直接注入进程列表走真实渲染路径。"""
        fill(list(items))

    win._dbg = {"state": state, "fill": _dbg_fill, "tv": tv, "kill": None,
                "retry": None}

    def alive():
        try:
            return bool(win.winfo_exists())
        except tk.TclError:
            return False

    def safe(fn, *a, **kw):
        """窗口可能已被用户关掉，所有 UI 更新都要过这一层。"""
        def wrapped():
            if alive():
                fn(*a, **kw)
        return wrapped

    def close(release=True):
        if state["closed"]:
            return
        state["closed"] = True
        try:
            if release:
                win.grab_release()
        except tk.TclError:
            pass
        try:
            win.destroy()
        except tk.TclError:
            pass

    def say(text, fg=MUTED):
        def do():
            status.configure(text=text, fg=fg)
        safe(do)()

    def refresh_total():
        if not alive():
            return
        n = sum(1 for v in state["checked"].values() if v)
        btn_kill.configure(text=f"结束选中并重试 ({n})")

    def toggle(iid):
        p = state["rows"].get(iid)
        if not p or is_protected(p["name"]) or state["busy"]:
            return
        state["checked"][iid] = not state["checked"].get(iid, False)
        tv.set(iid, "chk", BOX_ON if state["checked"][iid] else BOX_OFF)
        refresh_total()

    def on_click(e):
        if state["busy"]:
            return
        iid = tv.identify_row(e.y)
        if iid and tv.identify_column(e.x) == "#1":
            toggle(iid)
            return "break"

    tv.bind("<Button-1>", on_click)

    def fill(procs):
        if not alive():
            return
        tv.delete(*tv.get_children())
        state["rows"].clear()
        state["checked"].clear()
        if not procs:
            status.configure(
                text="没有找到占用进程。可能是系统缓存占用，或需要管理员权限；"
                     "也可能程序刚退出，直接点「只重试」即可。", fg=ORANGE)
            btn_kill.configure(text="结束选中并重试 (0)", state="disabled")
            return
        for i, p in enumerate(procs):
            prot = is_protected(p["name"])
            mem = p.get("mem_kb", 0)
            iid = tv.insert("", "end", values=(
                BOX_OFF if prot else BOX_ON, p["name"], p["pid"],
                p.get("parent", "—"),
                f"{mem:,} KB" if mem else "—",
                p["exe"] or p["app"] or "—"),
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

    def checked_rows():
        return [state["rows"][i] for i, v in state["checked"].items()
                if v and i in state["rows"]]

    # ------------------------------------------------------------- 结果反馈
    def done(ok, bad, locked_left, again_names, again_exes):
        """ok=成功结束数，bad=[(pid,err)]，locked_left=仍在占用的进程，
        again_names/again_exes=结束后又出现的程序（名字/路径）。"""
        state["busy"] = False
        if not alive():
            return
        safe(lambda: btn_kill.configure(state="normal"))()

        def unknown():
            """结束时没拿到新扫描结果，只能按计数判断。"""
            if bad:
                return "没能结束勾选的进程，占用程序仍在运行"
            if not ok:
                return "没有可结束的进程"
            return f"已结束 {ok} 个进程，但无法确认占用是否解除"

        if bad:
            win.grab_release()
            detail = "\n".join(f"PID {pid}：{err or '未知原因'}" for pid, err in bad[:5])
            if ok:
                tip = (f"成功 {ok} 个，失败 {len(bad)} 个。\n\n{detail}\n\n"
                       "失败通常是权限不足或进程受系统保护。\n"
                       "要现在重试迁移吗？")
            else:
                tip = (f"勾选的 {len(bad)} 个进程都没能结束。\n\n{detail}\n\n"
                       "多数情况下需要以管理员身份运行本程序。\n"
                       "要跳过结束进程、直接重试迁移吗？")
            title = "部分进程没能结束" if ok else "进程没能结束"
            _soon(lambda: _ask(
                title, tip, lambda: _retry(NOTE_RETRY, before=unknown),
                lambda: say("已取消，占用程序仍在运行", ORANGE)))
            return

        if not ok:
            say("没有可结束的进程，直接重试迁移", ORANGE)
            _retry_with_note("没有勾选任何进程，直接重试迁移")
            return

        if again_exes:
            say(f"已结束 {ok} 个进程，但同一程序又被重新拉起", ORANGE)
            win.grab_release()
            chain = next((p.get("parent") for p in again_names
                          if p.get("parent") not in (None, "—", "")), "")
            names = "、".join(sorted({p.get("name") or "?" for p in again_names}))
            hint = f"\n它是被「{chain}」拉起来的。" if chain else ""
            tip = (f"刚结束的「{names}」又出现了，说明有父进程在守护它。{hint}\n\n"
                   "结束进程治不了根——请按「谁拉起来的」这一列，"
                   "直接关掉最右边的那个程序（例如浏览器），再回来重试迁移。\n\n"
                   "要现在再试一次迁移吗？")
            _soon(lambda: _ask(
                "进程又被启动了", tip,
                lambda: _retry(NOTE_KILLED + "（进程曾被重新拉起）"),
                lambda: say("已暂停，请注意关闭守护它的父进程", ORANGE)))
            return

        if locked_left is None:
            say(f"已结束 {ok} 个进程，正在重试迁移", GREEN)
            _retry_with_note(f"已结束 {ok} 个进程（{state['killed_names']}），" + NOTE_KILLED)
            return

        if locked_left:
            names = "、".join(sorted({p.get("name") or "?" for p in locked_left}))
            say(f"已结束 {ok} 个进程，但仍有程序占用目录", ORANGE)
            win.grab_release()
            tip = (f"成功结束了 {ok} 个进程（{state['killed_names']}），"
                   f"但重新检测发现目录仍被占用：\n{names}\n\n"
                   "可能是父程序又把它们拉起来了，或者是系统索引 / 杀毒软件在扫描。\n\n"
                   "要现在再试一次迁移吗？（失败的话数据不会丢）")
            _soon(lambda: _ask(
                "目录仍被占用", tip, lambda: _retry(NOTE_KILLED),
                lambda: say("已暂停，请先关闭占用它的主程序", ORANGE)))
            return

        # 全部顺利
        say(f"已结束 {ok} 个进程，占用已解除，正在重试迁移", GREEN)
        _retry_with_note(f"已结束 {ok} 个进程（{state['killed_names']}），" + NOTE_KILLED)

    def _soon(fn):
        """把弹窗排到下一轮事件循环。

        注意不能用 win.after(0, fn)：这里的调用点都在 Dispatcher 的队列回调里，
        实测在这种上下文注册的 after 回调会静默不执行 —— 用户看到的就是
        「点了按钮，什么都没弹」。app.post 是已知可靠的通道。
        """
        app.post(lambda: alive() and fn())

    def _warn(title, text):
        from tkinter import messagebox
        if alive():
            messagebox.showwarning(title, text, parent=win)

    def _ask(title, text, on_yes, on_no):
        from tkinter import messagebox
        if not alive():
            return
        if messagebox.askyesno(title, text, parent=win):
            on_yes()
        elif on_no:
            on_no()

    def _retry_with_note(note):
        close()
        if on_retry:
            on_retry(note)

    def _retry(note=NOTE_RETRY, before=None):
        """close() 之后再写日志，所以先把要写的结论取出来。"""
        text = before() if before else ""
        close()
        if on_retry:
            on_retry(text or note)

    # ------------------------------------------------------------- 结束进程
    def do_kill():
        if state["busy"]:
            return
        rows = checked_rows()
        if not rows:
            say("没有勾选任何进程", ORANGE)
            _ask("没有勾选进程",
                 "你还没有勾选要结束的进程。\n\n要跳过这一步、直接重试迁移吗？",
                 lambda: _retry(NOTE_RETRY), lambda: None)
            return
        pids = [p["pid"] for p in rows]
        names = "、".join(sorted({p["name"] for p in rows}))
        from tkinter import messagebox
        if not messagebox.askyesno(
                "确认结束进程",
                f"即将强制结束 {len(pids)} 个进程：\n{names}\n\n"
                "未保存的数据会丢失。确定继续？", parent=win):
            say("已取消", MUTED)
            return

        state["busy"] = True
        state["killed_names"] = names
        state["killed_exes"] = {os.path.normcase(p["exe"]) for p in rows if p.get("exe")}
        btn_kill.configure(state="disabled")
        say("正在结束进程 … 请稍候", ACCENT)

        def job():
            ok, bad = kill_processes(pids)
            time.sleep(0.6)                 # 给 Windows 一点时间回收句柄
            try:
                left = work()               # 重新扫一遍：占用还在不在
            except Exception:
                return ok, bad, None, [], []
            left = left or []
            again = [p for p in left
                     if os.path.normcase(p.get("exe") or "") in state["killed_exes"]]
            return ok, bad, left, again, [p.get("exe") for p in again]

        run_async(app.post, job, lambda r: done(*r),
                  on_error=lambda e: _fail(e))

    def _fail(exc):
        state["busy"] = False
        if not alive():
            return
        say(f"结束进程时出错：{exc}", RED)
        _soon(lambda: _warn(
            "结束进程时出错",
            f"{exc}\n\n可以直接点「只重试」再试一次迁移，或手动关闭占用程序。"))
        try:
            btn_kill.configure(state="normal")
        except tk.TclError:
            pass

    def do_retry(note=NOTE_RETRY):
        close()
        if on_retry:
            on_retry(note)

    btn_kill = button(btns, "结束选中并重试 (0)", do_kill)
    btn_kill.pack(side="right")
    button(btns, "只重试", do_retry, "soft").pack(side="right", padx=8)
    button(btns, "取消", close, "ghost").pack(side="right")
    win._dbg.update({"kill": do_kill, "retry": do_retry, "status": status,
                     "btn_kill": btn_kill})

    def find_failed(exc):
        if alive():
            status.configure(text=f"查找占用进程失败：{exc}", fg=RED)
            btn_kill.configure(state="normal")

    run_async(app.post, work, fill, on_error=find_failed)
    return win
