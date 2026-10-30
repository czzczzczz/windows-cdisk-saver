# -*- coding: utf-8 -*-
"""界面冒烟测试：把每个页面的点击/双击回调都真实调用一遍。

这类 bug（回调签名不对、属性写错）在 pythonw 下只会静默失败，
必须靠测试兜住，而不是等用户点出来。
"""
from __future__ import annotations

import os
import sys
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
        from cdisk.pages.unlock import show_unlock

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
