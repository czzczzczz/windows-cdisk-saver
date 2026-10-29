# -*- coding: utf-8 -*-
"""系统垃圾清理：只处理确定可以重建/丢弃的缓存与临时文件。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import glob
import os
import shutil

from .util import CREATE_NO_WINDOW, dir_stats, is_admin, norm, rmtree_force, run


class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong)]


def recycle_info():
    try:
        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return int(info.i64NumItems), int(info.i64Size)
    except Exception:
        pass
    return 0, 0


def empty_recycle() -> bool:
    try:
        flags = 0x1 | 0x2 | 0x4  # 无确认 / 无进度 / 无声音
        return ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags) == 0
    except Exception:
        return False


class CleanItem:
    def __init__(self, cid, name, desc, paths=(), globs=(), cmd=None,
                 kind="dir", danger="safe", admin=False, slow=False, service=()):
        self.id = cid
        self.name = name
        self.desc = desc
        self.paths = [norm(p) for p in paths]
        self.globs = [norm(g) for g in globs]
        self.cmd = cmd
        self.kind = kind          # dir | glob | cmd | recycle | power
        self.danger = danger      # safe | caution | high
        self.admin = admin
        self.slow = slow
        self.service = service
        self._size = None

    def resolve(self):
        out = []
        for p in self.paths:
            if os.path.exists(p):
                out.append(p)
        for g in self.globs:
            out.extend(glob.glob(g))
        return list(dict.fromkeys(out))

    def size(self) -> int:
        if self.kind == "recycle":
            return recycle_info()[1]
        if self.kind == "cmd":
            return 0
        total = 0
        for p in self.resolve():
            if os.path.isdir(p):
                total += dir_stats(p)[1]
            else:
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
        return total

    def run(self, log=None) -> tuple:
        def L(m):
            if log:
                log(m)

        if self.kind == "recycle":
            ok = empty_recycle()
            return ok, "回收站已清空" if ok else "清空回收站失败"

        if self.kind == "cmd":
            L(f"执行：{self.cmd}")
            rc, out, err = run(["cmd", "/c", self.cmd], timeout=1800)
            ok = rc == 0
            return ok, (out or err or "").strip()[-400:] or ("成功" if ok else f"失败 code={rc}")

        freed = 0
        for p in self.resolve():
            if os.path.isdir(p) and not os.path.islink(p):
                try:
                    before = dir_stats(p)[1]
                except Exception:
                    before = 0
                if self.id in ("user_temp", "win_temp", "inet_cache", "prefetch"):
                    # 目录本身保留，只清内容（某些程序依赖目录存在）
                    for name in os.listdir(p):
                        rmtree_force(os.path.join(p, name))
                else:
                    rmtree_force(p)
                try:
                    after = dir_stats(p)[1] if os.path.isdir(p) else 0
                except Exception:
                    after = 0
                freed += max(0, before - after)
            else:
                try:
                    sz = os.path.getsize(p)
                    os.remove(p)
                    freed += sz
                except OSError:
                    pass
        return True, f"释放约 {freed/1024/1024:.0f} MB"


def _w() -> str:
    return os.environ.get("WINDIR", r"C:\Windows")


ITEMS = [
    CleanItem("user_temp", "用户临时文件", "当前账户的 %TEMP% 内容，正在运行的程序会占用部分文件",
              paths=["%TEMP%"], danger="safe"),
    CleanItem("win_temp", "Windows 临时文件", "系统级临时目录，安装程序残留常堆在这里",
              paths=[os.path.join(_w(), "Temp")], admin=True, danger="safe"),
    CleanItem("inet_cache", "IE / 系统网络缓存", "WinINet 缓存，浏览器与系统更新共用",
              paths=["%LOCALAPPDATA%\\Microsoft\\Windows\\INetCache"], danger="safe"),
    CleanItem("crash", "崩溃转储文件", "程序崩溃时生成的 dump，单个可达数 GB",
              paths=["%LOCALAPPDATA%\\CrashDumps", os.path.join(_w(), "Minidump"),
                     os.path.join(_w(), "LiveKernelReports"),
                     os.path.join(_w(), "MEMORY.DMP")], danger="safe"),
    CleanItem("thumb", "缩略图 / 图标缓存", "资源管理器生成的缓存库，会自动重建",
              globs=["%LOCALAPPDATA%\\Microsoft\\Windows\\Explorer\\thumbcache_*.db",
                     "%LOCALAPPDATA%\\Microsoft\\Windows\\Explorer\\iconcache_*.db"],
              danger="safe"),
    CleanItem("prefetch", "预读取文件 Prefetch", "加速启动的预读数据，删除后首次启动略慢",
              paths=[os.path.join(_w(), "Prefetch")], admin=True, danger="caution"),
    CleanItem("wu_cache", "Windows 更新下载缓存", "已下载的更新包，删除不影响已安装更新",
              paths=[os.path.join(_w(), "SoftwareDistribution", "Download")],
              admin=True, danger="caution", service=("wuauserv", "bits")),
    CleanItem("delivery", "传递优化缓存", "Windows 用于 P2P 分发的更新副本",
              kind="cmd", cmd='powershell -NoProfile -Command "Delete-DeliveryOptimizationCache -Force"',
              admin=True, danger="caution"),
    CleanItem("recycle", "回收站", "所有分区回收站内的文件", kind="recycle", danger="caution"),
    CleanItem("cbs_logs", "组件服务日志 CBS", "Windows 组件安装日志，动辄上 GB",
              paths=[os.path.join(_w(), "Logs", "CBS")], admin=True, danger="safe"),
    CleanItem("old_windows", "旧版 Windows 安装 (Windows.old)", "升级系统留下的回滚副本，删除后无法回退旧版本",
              paths=[os.path.join(os.path.splitdrive(_w())[0] + "\\", "Windows.old")],
              admin=True, danger="high"),
    CleanItem("winsxs", "组件存储清理 (DISM)", "清理 WinSxS 中的旧组件，耗时较长，之后无法卸载已装更新",
              kind="cmd",
              cmd='dism /online /cleanup-image /startcomponentcleanup /resetbase',
              admin=True, slow=True, danger="high"),
    CleanItem("hiberfil", "关闭休眠文件 hiberfil.sys", "可释放约等于内存 40%~100% 的空间，会关闭快速启动",
              kind="cmd", cmd="powercfg /h off", admin=True, danger="high"),
]


def by_id(cid):
    for it in ITEMS:
        if it.id == cid:
            return it
    return None
