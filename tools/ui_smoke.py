# -*- coding: utf-8 -*-
"""界面冒烟测试：把每个页面的点击/双击回调都真实调用一遍。

这类 bug（回调签名不对、属性写错）在 pythonw 下只会静默失败，
必须靠测试兜住，而不是等用户点出来。
"""
from __future__ import annotations

import os
import shutil
import sys
import time
import traceback
from types import SimpleNamespace

import tkinter as tk

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import cdisk.util as U                      # noqa: E402
import main as M                            # noqa: E402
from tkinter import messagebox              # noqa: E402

# 让所有对话框不阻塞测试
messagebox.showinfo = lambda *a, **k: "ok"
messagebox.showerror = lambda *a, **k: "ok"
messagebox.showwarning = lambda *a, **k: "ok"
messagebox.askyesno = lambda *a, **k: False

# 不真的打开资源管理器
U.open_in_explorer = lambda *a, **k: None

FAILS = []
OKS = []


def check(name, fn):
    try:
        fn()
        OKS.append(name)
        print(f"  ✔ {name}")
    except Exception as exc:  # noqa: BLE001
        FAILS.append((name, traceback.format_exc()))
        print(f"  ✘ {name}: {type(exc).__name__}: {exc}")


def ev_at(tree, iid, col):
    bbox = tree.bbox(iid, col)
    if not bbox:
        return None
    x, y, w, h = bbox
    return SimpleNamespace(x=x + w // 2, y=y + h // 2, widget=tree)


def main():
    root = tk.Tk()
    M._install_error_hooks(root)
    app = M.App(root)
    state = {"i": 0}

    def wait_ready():
        state["i"] += 1
        mp = app.pages["migrate"]
        if mp.rows and not mp.busy:
            run(); return
        if state["i"] > 120:
            print("TIMEOUT 等待扫描")
            root.destroy(); return
        root.after(300, wait_ready)

    def run():
        print("\n[1] 概览页")
        check("overview.refresh", lambda: app.pages["overview"].refresh())

        print("\n[2] 迁移页")
        mp = app.pages["migrate"]
        app.open_page("migrate")
        root.update()

        check("migrate.on_show", lambda: mp.on_show())
        check("migrate.show_help 打开说明窗", mp.show_help)
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel) and w.title() == "迁移原理":
                w.destroy()

        def toggle_first():
            oks = [i for i, r in mp.rows.items() if r["state"] == "ok"]
            if not oks:
                print("    （跳过：当前没有「可迁移」项，可能都已迁移或未安装）")
                return
            iid = oks[0]
            e = ev_at(mp.tree, iid, "#1")
            assert e is not None, "取不到勾选列坐标"
            before = mp.tree.set(iid, "chk")
            mp._on_click(e)
            mid = mp.tree.set(iid, "chk")
            assert mid != before, f"点击没有改变状态（{before} -> {mid}）"
            mp._on_click(e)
            assert mp.tree.set(iid, "chk") == before, "再次点击没有还原"
        check("migrate._on_click 勾选/取消", toggle_first)

        def dbl():
            iid = next(iter(mp.rows))
            mp.tree.selection_set(iid)
            mp._on_dbl(SimpleNamespace(x=1, y=1, widget=mp.tree))
        check("migrate._on_dbl 双击", dbl)

        check("migrate.select_all", mp.select_all)
        check("migrate.select_none", mp.select_none)
        check("migrate._update_sel", mp._update_sel)

        def custom_dlg():
            w = mp.custom_dialog()
            root.update()
            assert w.winfo_exists(), "对话框没创建出来"
            var = tk.StringVar(value=os.environ["USERPROFILE"])
            mp._probe_custom(var)
            root.update()
            w.destroy()
        check("migrate.custom_dialog 打开/关闭", custom_dlg)

        def empty_migrate():
            mp.select_none()
            mp.tree.selection_remove(*mp.tree.selection())
            mp.migrate_selected()          # 应弹提示，不应抛异常
        check("migrate.migrate_selected 空选兜底", empty_migrate)

        print("\n[3] 空间分析页")
        ap = app.pages["analyze"]
        app.open_page("analyze")
        root.update()
        check("analyze._pick 取消路径选择", lambda: None)
        check("analyze._on_open 空树", lambda: ap._on_open(SimpleNamespace()))
        check("analyze._on_dbl 空树", lambda: ap._on_dbl(SimpleNamespace()))
        check("analyze._open_big 空树", lambda: ap._open_big(SimpleNamespace()))
        check("analyze._stop", ap._stop)

        print("\n[4] 写入监控页")
        mop = app.pages["monitor"]
        app.open_page("monitor")
        root.update()
        check("monitor.on_show", mop.on_show)
        check("monitor.clear_live", mop.clear_live)
        check("monitor._refresh_rank", mop._refresh_rank)
        check("monitor._min_size", lambda: mop._min_size())
        check("monitor._refresh_snap_label", mop._refresh_snap_label)
        check("monitor.do_diff 快照不足", mop.do_diff)
        check("monitor._open_live 空", lambda: mop._open_live(SimpleNamespace()))
        check("monitor._open_diff 空", lambda: mop._open_diff(SimpleNamespace()))
        check("monitor.migrate_selected_dir 空选", mop.migrate_selected_dir)

        from cdisk.pages.monitor_page import app_dir_of, bucket_of
        HOME = os.environ["USERPROFILE"]

        def path_case(name, path, expect):
            check(name, lambda: (_ for _ in ()).throw(
                AssertionError(f"得到 {app_dir_of(path)!r}，期望 {expect!r}"))
                if os.path.normcase(app_dir_of(path)) != os.path.normcase(expect) else None)

        path_case("app_dir_of 用户目录下的点目录",
                  os.path.join(HOME, ".workbuddy-ai", "logs", "a.log"),
                  os.path.join(HOME, ".workbuddy-ai"))
        path_case("app_dir_of AppData\\Local\\<软件>",
                  os.path.join(HOME, "AppData", "Local", "Foo", "bar", "a.log"),
                  os.path.join(HOME, "AppData", "Local", "Foo"))
        path_case("app_dir_of Documents\\<软件>",
                  os.path.join(HOME, "Documents", "Tencent Files", "1", "a.dat"),
                  os.path.join(HOME, "Documents", "Tencent Files"))
        check("bucket_of AppData\\Local\\Tencent",
              lambda: (_ for _ in ()).throw(AssertionError("归类错误"))
              if bucket_of(r"C:\Users\x\AppData\Local\Tencent\a.dat") != r"AppData\Local\Tencent"
              else None)

        print("\n[4b] 智能发现规则")
        from cdisk.discover import _builtin_bases, _covered, _risk, _skip

        def expect(cond, msg):
            if not cond:
                raise AssertionError(msg)

        check("排除 AppData\\Local\\Programs（已安装程序）",
              lambda: expect(_skip(os.path.join(HOME, "AppData", "Local", "Programs")),
                             "Programs 应该被排除"))
        check("排除 AppData\\Roaming\\npm（全局包）",
              lambda: expect(_skip(os.path.join(HOME, "AppData", "Roaming", "npm")),
                             "npm 应该被排除"))
        check("排除 Desktop（个人文件）",
              lambda: expect(_skip(os.path.join(HOME, "Desktop")), "Desktop 应该被排除"))
        check("不排除普通软件目录",
              lambda: expect(not _skip(os.path.join(HOME, "AppData", "Local", "OpenAI")),
                             "OpenAI 不该被排除"))
        check("内置目标已覆盖的目录被去重",
              lambda: expect(_covered(os.path.join(HOME, "AppData", "Local", "pip"), _builtin_bases()),
                             "pip 属于内置目标，应该被去重"))
        check("风险分级：缓存目录=安全",
              lambda: expect(_risk(r"C:\x\AppData\Local\Foo\cache") == "safe", "cache 应为 safe"))
        check("风险分级：普通目录=谨慎",
              lambda: expect(_risk(r"C:\x\AppData\Roaming\Tencent") == "caution", "应为 caution"))

        print("\n[4c] 占用检测与「关闭占用」对话框")
        from cdisk.handles import is_protected, using_processes
        from cdisk.migrate import is_lock_error
        from cdisk.pages.unlock import show_unlock

        check("robocopy code=9 判为占用失败",
              lambda: expect(is_lock_error("有文件没能复制（robocopy code=9）：文件正被程序占用"),
                             "code=9 应触发关闭占用"))
        check("WinError 5 判为占用失败",
              lambda: expect(is_lock_error("源目录被占用或权限不足（WinError 5）"),
                             "WinError 5 应触发关闭占用"))
        check("磁盘已满不判为占用",
              lambda: expect(not is_lock_error("复制失败（robocopy code=16）：目标磁盘已满"),
                             "磁盘满不该弹关闭占用"))
        check("空间预检提示不判为占用",
              lambda: expect(not is_lock_error("目标盘空间不足：需要约 3 GB"),
                             "空间不足不该弹关闭占用"))

        check("using_processes 对不存在的路径返回空",
              lambda: expect(using_processes(os.path.join(HOME, "_no_such_dir_xyz")) == [],
                             "不存在的目录应返回空列表"))
        check("系统关键进程受保护",
              lambda: expect(is_protected("explorer.exe") and is_protected("lsass.exe"),
                             "explorer/lsass 应受保护"))
        check("普通程序不受保护",
              lambda: expect(not is_protected("WeChat.exe"), "WeChat 不该受保护"))

        def unlock_dlg():
            w = show_unlock(root, app, [os.path.join(HOME, "AppData", "Local")], None)
            root.update()
            assert w.winfo_exists(), "对话框没创建出来"
            w.grab_release()
            w.destroy()
        check("unlock 对话框 打开/关闭", unlock_dlg)

        print("\n[4d] 「结束进程」全链路：每个分支都必须有可见反馈")
        from cdisk.pages import unlock as UU

        _info, _warn = messagebox.showinfo, messagebox.showwarning
        VICTIM = [{"pid": 90001, "name": "host.exe", "exe": r"C:\x\host.exe",
                   "app": "host", "parent": "—", "mem_kb": 1024, "type": "未知"},
                  {"pid": 90002, "name": "child.exe", "exe": r"C:\x\child.exe",
                   "app": "child", "parent": "host.exe", "mem_kb": 2048, "type": "未知"}]

        def case(kill_ret, rescan, answer=True, result=False):
            """跑一个场景：打开对话框 → 注入进程 → 点「结束选中并重试」→ 等结束。

            answer 回答「确认结束进程」，result 回答结果框里的「要重试吗」。
            返回 (弹过的提示标题, on_retry 收到的说明, 结束时的状态栏文字)。
            """
            popups = []
            got = {"retry": [], "status": ""}
            ok, bad = kill_ret
            o_use, o_kill = UU.using_processes, UU.kill_processes

            def fake_yesno(title="", *a, **k):
                # 「确认结束进程」用 answer，其余（结果反馈框）用 result
                hit = answer if title == "确认结束进程" else result
                if title != "确认结束进程":
                    popups.append(title)      # 结果框本身就是反馈
                return hit
            messagebox.askyesno = fake_yesno
            messagebox.showwarning = lambda t, m="", **k: popups.append(t) or "ok"
            messagebox.showinfo = lambda t, m="", **k: popups.append(t) or "ok"

            def fake_use(p, limit=320, extra_files=None):
                # 第一次（对话框打开）给占用列表；之后的重扫给 rescan
                return list(VICTIM) if not fake_use.called else list(rescan)
            fake_use.called = False

            # 不真的去独占探测整个 AppData\Local（慢且与本用例无关）
            o_lk = UU.locked_files
            UU.locked_files = lambda p, limit=120, budget=1500: []


            def fake_kill(pids):
                fake_use.called = True
                return ok, bad

            UU.using_processes = fake_use
            UU.kill_processes = fake_kill
            w = None
            try:
                w = show_unlock(root, app, [os.path.join(HOME, "AppData", "Local")],
                                lambda note="": got["retry"].append(note))
                dbg = w._dbg
                dbg["fill"](VICTIM)          # 注入，走真实渲染与勾选逻辑
                root.update()
                assert dbg["state"]["rows"], "注入后表格仍为空"
                dbg["kill"]()

                deadline = time.time() + 2.2
                fin = {"v": False}

                def stop():
                    fin["v"] = True

                def poll():
                    # 固定留 2.2s 观察窗口：弹窗在 done() 里排队，
                    # 早退会读到「还没弹」的中间态
                    if time.time() > deadline:
                        stop()
                        return
                    root.after(40, poll)
                t0 = time.time()
                root.after(40, poll)
                root.after(2600, stop)
                # 保险：任何情况下 4 秒后都要退出这一轮（grab 被抢占时 mainloop 会饿死）
                root.after(4000, lambda: root.quit())

                # 必须走真正的 mainloop：在 Python 栈上用 update() 死转，
                # done() 里排队的提示框永远等不到执行窗口，测试就会误判成
                # 「什么都没弹」——而这恰恰是用户报的那个 bug 的假象。
                root.mainloop()
                # 等 done() 之后的收尾（关窗 → 后续回调）真正跑完
                try:
                    got["status"] = dbg["status"].cget("text")
                except tk.TclError:
                    pass

            finally:
                UU.using_processes, UU.kill_processes = o_use, o_kill
                UU.locked_files = o_lk
                # 清干净：残留的 grab 会让下一个场景的事件循环卡死
                for tw in list(root.winfo_children()):
                    if isinstance(tw, tk.Toplevel) and tw.title() == "关闭占用程序":
                        try:
                            tw.grab_release()
                            tw.destroy()
                        except tk.TclError:
                            pass
                try:
                    root.grab_release()
                except tk.TclError:
                    pass
                root.update()
            return popups, got["retry"], got["status"]

        def expect(cond, msg):
            if not cond:
                raise AssertionError(msg)

        def case_ok():
            tips, retry, st = case((2, []), [])       # 全成功、占用已解除
            expect(retry, "成功结束时必须调用重试，否则用户看不到任何结果")
            expect("结束" in retry[0], f"重试说明里要写清做了什么，实际：{retry[0]}")
            return tips, retry, st

        def case_all_fail():
            tips, retry, st = case((0, [(90001, "拒绝访问"), (90002, "拒绝访问")]), [])
            expect("进程没能结束" in tips, f"全部失败必须弹提示，实际 {tips}")
            expect("占用程序仍在运行" in st, f"状态栏也要说明，实际 {st!r}")

        def case_part_fail():
            tips, retry, st = case((1, [(90002, "拒绝访问")]), VICTIM)
            expect("部分进程没能结束" in tips, f"部分失败要弹提示，实际 {tips}")

        def case_reborn():
            tips, retry, st = case((2, []), VICTIM)   # 杀完占用还在、还是同一程序
            expect("进程又被启动了" in tips, f"被杀后又出现要明确告知，实际 {tips}")
            expect("已暂停" in st, f"答否后状态栏要说明，实际 {st!r}")

        def case_still_locked():
            other = [{"pid": 91001, "name": "other.exe", "exe": r"C:\x\other.exe",
                      "app": "other", "parent": "—", "mem_kb": 1, "type": "未知"}]
            tips, retry, st = case((2, []), other)     # 杀干净了，但还有别的程序占用
            expect("目录仍被占用" in tips, f"仍有其它占用要说明，实际 {tips}")

        def case_cancel_confirm():
            tips, retry, st = case((2, []), [], answer=False)
            expect(not retry and not tips, "用户在确认框点取消时不应有任何动作")
            expect("取消" in st, f"取消后状态栏要说明，实际 {st!r}")

        def case_retry_on_yes():
            # 全部失败后点「是」→ 必须真的走重试，并把原因带出去
            tips, retry, st = case((0, [(90001, "拒绝访问")]), [], result=True)
            expect(retry and "没能结束" in retry[0],
                   f"同意重试时应把失败原因带给调用方，实际 {retry}")

        check("结束进程：全部成功 → 有说明并自动重试", case_ok)
        check("结束进程：全部失败 → 弹「进程没能结束」", case_all_fail)
        check("结束进程：部分失败 → 弹提示", case_part_fail)
        check("结束进程：被杀后又出现 → 弹「进程又被启动了」", case_reborn)
        check("结束进程：占用仍在（别的程序）→ 弹「目录仍被占用」", case_still_locked)
        check("结束进程：确认框点取消 → 状态栏说明", case_cancel_confirm)
        check("结束进程：失败后同意重试 → 带上原因", case_retry_on_yes)

        # 自己/自己的祖先进程绝不能进 taskkill —— 否则点了按钮界面直接消失
        from cdisk.handles import _pids_to_keep
        check("kill 黑名单包含自身进程",
              lambda: expect(__import__("os").getpid() in _pids_to_keep(),
                             "自身 PID 必须排除"))
        check("kill 黑名单包含父进程",
              lambda: expect(len(_pids_to_keep()) >= 2,
                             "至少要排除自己和父进程"))

        def kill_self_guard():
            real = UU.kill_processes
            called = []
            import cdisk.handles as HH
            orig_run = HH.run if hasattr(HH, "run") else None
            import cdisk.util as _u
            saved = _u.run
            _u.run = lambda *a, **k: called.append(a) or (0, "", "")
            try:
                ok, bad = real([os.getpid()])
            finally:
                _u.run = saved
            expect(ok == 0 and bad, f"结束自身必须被拒绝，实际 ok={ok} bad={bad}")
            expect(not called, f"不应真的调用 taskkill，实际 {called}")
        check("kill_processes 拒绝结束自身", kill_self_guard)

        messagebox.showinfo, messagebox.showwarning = _info, _warn

        print("\n[4e] 占用检测精度 + 部分迁移")
        from cdisk.handles import _sample_files, is_locked_file
        from cdisk.migrate import list_subdirs, partial_migrate
        from cdisk.util import is_junction

        def sample_covers_root():
            """根目录下的文件必须被采样到——旧实现会被大子目录吃光预算。"""
            tmp = os.path.join(os.environ["TEMP"], "_cdisk_sample_test")
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp)
            try:
                key = os.path.join(tmp, "important.db")
                open(key, "wb").write(b"x" * 100)
                big = os.path.join(tmp, "bigdir")
                os.makedirs(big)
                for i in range(3000):
                    open(os.path.join(big, f"f{i}.txt"), "wb").write(b"y")
                got = {os.path.normcase(p) for p in _sample_files(tmp, limit=60)}
                expect(os.path.normcase(key) in got,
                       "根目录文件没被采样到（预算被 bigdir 吃光了）")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        check("采样必须覆盖根目录文件", sample_covers_root)

        def lock_probe():
            tmp = os.path.join(os.environ["TEMP"], "_cdisk_lock_test")
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp)
            try:
                free = os.path.join(tmp, "free.txt")
                open(free, "wb").write(b"x" * 100)
                expect(not is_locked_file(free), "未锁文件被误判为被锁")
                expect(is_locked_file(os.path.join(tmp, "_nope_xyz")) is False,
                       "不存在的文件不该算作被锁")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        check("独占锁探测不误报", lock_probe)

        def partial_case():
            """三个子目录，中间一个被独占锁：可迁的迁走，被锁的原样保留。"""
            base = os.path.join(os.environ["USERPROFILE"], "_cdisk_partial_smoke")
            root = os.path.join(base, "data")
            # 必须跨盘，否则 migrate_job 会拒绝
            other = "D:" if os.path.splitdrive(
                os.environ["USERPROFILE"])[0].upper() != "D:" else "C:"
            dest = os.path.join(other + "\\", "_cdisk_partial_dst")
            shutil.rmtree(base, ignore_errors=True)
            shutil.rmtree(dest, ignore_errors=True)
            try:
                for name in ("aaa", "bbb", "ccc"):
                    d = os.path.join(root, name)
                    os.makedirs(d)
                    for i in range(4):
                        open(os.path.join(d, f"f{i}.bin"), "wb").write(b"Z" * 8000)

                expect(len(list_subdirs(root)) == 3, "子目录枚举数量不对")

                import ctypes
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                k32.CreateFileW.restype = ctypes.c_void_p
                locked = os.path.join(root, "bbb", "f0.bin")
                h = k32.CreateFileW(locked, 0x80000000, 0, None, 3, 0x80, None)
                expect(h and h != 0xFFFFFFFFFFFFFFFF, "无法造出独占占用")
                try:
                    expect(is_locked_file(locked), "独占占用没被探测出来")
                    ok_n, fails, freed = partial_migrate(root, dest)
                    expect(ok_n == 2, f"应该迁走 2 个，实际 {ok_n}")
                    expect(len(fails) == 1, f"应该跳过 1 个，实际 {len(fails)}")
                    expect(is_junction(os.path.join(root, "aaa")), "aaa 应已变成联接")
                    expect(is_junction(os.path.join(root, "ccc")), "ccc 应已变成联接")
                    expect(not is_junction(os.path.join(root, "bbb")),
                           "bbb 被锁，不该被迁移")
                    expect(len(os.listdir(os.path.join(root, "bbb"))) == 4,
                           "bbb 的文件必须原样保留")
                finally:
                    k32.CloseHandle(ctypes.c_void_p(h))
            finally:
                shutil.rmtree(base, ignore_errors=True)
                shutil.rmtree(dest, ignore_errors=True)
        check("部分迁移：跳过被锁子目录，数据零损失", partial_case)

        print("\n[5] 系统清理页")
        cp = app.pages["clean_page"] if "clean_page" in app.pages else app.pages["clean"]
        app.open_page("clean")
        root.update()
        check("clean.select_safe", cp.select_safe)

        def clean_click():
            iid = next(iter(cp.rows))
            e = ev_at(cp.tree, iid, "#1")
            assert e is not None, "取不到勾选列坐标"
            before = cp.tree.set(iid, "chk")
            cp._on_click(e)
            mid = cp.tree.set(iid, "chk")
            assert mid != before, f"点击没有改变状态（{before} -> {mid}）"
            cp._on_click(e)
            assert cp.tree.set(iid, "chk") == before, "再次点击没有还原"
        check("clean._on_click 勾选/取消", clean_click)
        check("clean._update_total", cp._update_total)

        print("\n[6] 迁移记录页")
        hp = app.pages["history"]
        app.open_page("history")
        root.update()
        check("history.refresh", hp.refresh)
        check("history.open_dst 空选中", hp.open_dst)

        print("\n" + "=" * 50)
        print(f"通过 {len(OKS)} 项，失败 {len(FAILS)} 项")
        if FAILS:
            for name, tb in FAILS:
                print(f"\n--- {name} ---\n{tb}")
        root.destroy()
        sys.exit(1 if FAILS else 0)

    root.after(800, lambda: app.open_page("migrate"))
    root.after(1200, wait_ready)
    root.mainloop()


if __name__ == "__main__":
    main()
