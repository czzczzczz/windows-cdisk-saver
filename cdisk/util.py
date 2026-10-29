# -*- coding: utf-8 -*-
"""通用工具：路径处理、配置存储、权限、目录统计、系统调用。"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import stat as stat_mod
import subprocess
import sys
import time

APP_NAME = "CDiskSaver"
CREATE_NO_WINDOW = 0x08000000
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
IO_REPARSE_TAG_SYMLINK = 0xA000000C


# ---------------------------------------------------------------- 路径 / 配置
def app_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def data_path(name: str) -> str:
    return os.path.join(app_dir(), name)


def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def norm(p: str) -> str:
    if not p:
        return p
    return os.path.normpath(os.path.expandvars(os.path.expanduser(p)))


def human(n) -> str:
    if n is None:
        return "-"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    neg = n < 0
    n = abs(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                s = f"{int(n)} B"
            elif n < 10:
                s = f"{n:.2f} {unit}"
            else:
                s = f"{n:.1f} {unit}"
            return ("-" if neg else "") + s
        n /= 1024.0
    return "-"


def drive_of(path: str) -> str:
    d = os.path.splitdrive(os.path.abspath(path))[0]
    return d.upper() or "C:"


def free_bytes(path: str) -> int:
    try:
        return shutil.disk_usage(path).free
    except Exception:
        try:
            return shutil.disk_usage(os.path.splitdrive(path)[0] + "\\").free
        except Exception:
            return 0


def usage(path: str):
    try:
        return shutil.disk_usage(path)
    except Exception:
        return None


# ---------------------------------------------------------------- 权限 / 进程
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run(args, timeout=None, capture=True):
    """静默执行命令，返回 (returncode, stdout, stderr)。"""
    try:
        p = subprocess.run(
            args,
            capture_output=capture,
            text=True,
            errors="ignore",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -9, "", "timeout"
    except Exception as exc:  # noqa: BLE001
        return -1, "", str(exc)


def popen_quiet(args):
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def relaunch_as_admin() -> bool:
    """以管理员身份重启自身（打包后为 exe，源码为 python 脚本）。"""
    try:
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, ""
        else:
            exe = sys.executable
            params = '"%s"' % os.path.abspath(sys.argv[0])
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return rc > 32
    except Exception:
        return False


def open_in_explorer(path: str) -> None:
    try:
        if os.path.isdir(path):
            os.startfile(path)  # noqa: S606
        else:
            subprocess.Popen(["explorer", "/select,", path])
    except Exception:
        pass


# ---------------------------------------------------------------- 链接 / 统计
def reparse_tag(path: str) -> int:
    try:
        st = os.stat(path, follow_symlinks=False)
        return int(getattr(st, "st_reparse_tag", 0) or 0)
    except OSError:
        return 0


def is_junction(path: str) -> bool:
    return reparse_tag(path) == IO_REPARSE_TAG_MOUNT_POINT


def is_any_link(path: str) -> bool:
    return reparse_tag(path) in (IO_REPARSE_TAG_MOUNT_POINT, IO_REPARSE_TAG_SYMLINK)


def junction_target(path: str) -> str:
    """读取 junction 指向的真实目录（best effort）。"""
    try:
        out = subprocess.run(
            ["cmd", "/c", "dir", "/AL", os.path.dirname(path) or "."],
            capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW,
        ).stdout
        name = os.path.basename(path.rstrip("\\"))
        for line in out.splitlines():
            if name.upper() in line.upper() and ("JUNCTION" in line.upper() or "[" in line):
                if "[" in line and "]" in line:
                    return line[line.rfind("[") + 1: line.rfind("]")]
    except Exception:
        pass
    return ""


def dir_stats(root: str, skip_links: bool = True, cancel=None):
    """返回 (文件数, 总字节)。跳过 junction/symlink，避免重复计算与死循环。"""
    if skip_links and reparse_tag(root):
        # 根路径本身是联接时不统计，否则会把 D 盘的数据算到 C 盘头上
        return 0, 0
    files = 0
    size = 0
    stack = [root]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if skip_links and e.is_symlink():
                                continue
                            if skip_links and reparse_tag(e.path):
                                continue
                            stack.append(e.path)
                        else:
                            st = e.stat(follow_symlinks=False)
                            size += st.st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return files, size


def quick_size(path: str) -> int:
    """尽量快的大小估算（用于列表展示）。"""
    if not os.path.exists(path):
        return 0
    if not os.path.isdir(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    return dir_stats(path)[1]


def rmtree_force(path: str, progress=None, cancel=None) -> bool:
    """删除目录，忽略只读/占用错误，返回是否彻底删除。"""
    if not os.path.exists(path):
        return True

    def onerr(func, p, exc_info):
        try:
            os.chmod(p, stat_mod.S_IWRITE)
            func(p)
        except Exception:
            pass

    try:
        shutil.rmtree(path, onerror=onerr)
    except Exception:
        pass
    return not os.path.exists(path)


def kill_process_by_name(names) -> None:
    for n in names:
        run(["taskkill", "/F", "/IM", n])


def is_running(exe_names) -> bool:
    rc, out, _ = run(["tasklist", "/FO", "CSV", "/NH"])
    if rc != 0:
        return False
    low = out.lower()
    return any(n.lower() in low for n in exe_names)


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
