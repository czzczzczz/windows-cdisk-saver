# -*- coding: utf-8 -*-
"""界面自动测试：驱动迁移页勾选逻辑并截图，验证多选框可用。"""
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

from main import App                       # noqa: E402
import shot                                # noqa: E402


def main():
    root = tk.Tk()
    app = App(root)
    page = app.pages["migrate"]
    state = {"n": 0}

    def wait_scan():
        state["n"] += 1
        if page.rows and not page.busy:
            root.after(400, step_click)
            return
        if state["n"] > 400:
            print("TIMEOUT waiting scan, rows =", len(page.rows))
            root.destroy()
            return
        root.after(300, wait_scan)

    def step_click():
        app.open_page("migrate")
        root.update()

        # 1) 单个勾选
        target_iid = None
        for iid, r in page.rows.items():
            if r["state"] == "ok":
                target_iid = iid
                break
        if not target_iid:
            print("NO MIGRATABLE ROW")
            root.destroy()
            return
        tid = page.rows[target_iid]["t"].id
        before = page.tree.set(target_iid, "chk")
        page._toggle(target_iid)
        after = page.tree.set(target_iid, "chk")
        print(f"[单勾] {page.rows[target_iid]['t'].name}: {before} -> {after} "
              f"checked={page.checked[tid]}")

        # 2) 不可迁移的行不能勾
        for iid, r in page.rows.items():
            if r["state"] in ("none", "manual", "done"):
                b = page.tree.set(iid, "chk")
                page._toggle(iid)
                a = page.tree.set(iid, "chk")
                print(f"[拒勾] {r['t'].name}({r['state']}): {b} -> {a}")
                break

        # 3) 全选
        page.select_none()
        print("清空后:", page.lbl_sel.cget("text"))
        page.select_all()
        print("全选后:", page.lbl_sel.cget("text"),
              "| 按钮:", page.btn_go.cget("text"),
              "| 按钮状态:", page.btn_go.cget("state"))

        n_ok = sum(1 for r in page.rows.values() if r["state"] in ("ok", "part"))
        n_checked = sum(1 for r in page.rows.values()
                        if page.checked.get(r["t"].id) and r["state"] in ("ok", "part"))
        print(f"[一致性] 可迁移 {n_ok} 项，已勾 {n_checked} 项 -> "
              f"{'OK' if n_ok == n_checked else 'MISMATCH'}")

        root.update()
        root.after(600, lambda: finish(target_iid))

    def finish(iid):
        page.select_all()
        root.update()
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        hwnd = ctypes.windll.user32.FindWindowW(None, "C 盘空间管家 v1.0.0")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            import time
            time.sleep(0.8)
            import ctypes.wintypes as wt
            r = wt.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
            out = os.path.join(HERE, "_ui_migrate.png")
            shot.capture(r.left, r.top, r.right - r.left, r.bottom - r.top, out)
            print("shot ->", out)
        root.destroy()

    root.after(800, wait_scan)
    root.after(900, lambda: app.open_page("migrate"))
    root.mainloop()


if __name__ == "__main__":
    main()
