# -*- coding: utf-8 -*-
"""找出「谁占用了这个目录」，并支持结束进程。

用 Windows Restart Manager（RstrtMgr.dll）——它就是给安装程序用来检测
「哪些程序正占用我要替换的文件」的，比自己枚举句柄可靠得多。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os

CCH_RM_SESSION_KEY = 32
CCH_RM_MAX_APP_NAME = 255
CCH_RM_MAX_SVC_NAME = 63
ERROR_SUCCESS = 0
ERROR_MORE_DATA = 234

RM_APP_TYPE = {
    1000: "未知", 1001: "主窗口", 1002: "其他窗口", 1003: "服务",
    1004: "资源管理器", 1005: "控制台", 1006: "关键进程",
}


class RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [("dwProcessId", wt.DWORD), ("ProcessStartTime", wt.FILETIME)]


class RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [
        ("Process", RM_UNIQUE_PROCESS),
        ("strAppName", wt.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
        ("strServiceShortName", wt.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
        ("ApplicationType", ctypes.c_uint),
        ("AppStatus", wt.ULONG),
        ("TSSessionId", wt.DWORD),
        ("bRestartable", wt.BOOL),
    ]


try:
    _rm = ctypes.WinDLL("RstrtMgr")
    _rm.RmStartSession.argtypes = [ctypes.POINTER(wt.DWORD), wt.DWORD,
                                   wt.LPWSTR]
    _rm.RmRegisterResources.argtypes = [wt.DWORD, wt.UINT,
                                        ctypes.POINTER(wt.LPCWSTR), wt.UINT,
                                        ctypes.c_void_p, wt.UINT,
                                        ctypes.POINTER(wt.LPCWSTR)]
    _rm.RmGetList.argtypes = [wt.DWORD, ctypes.POINTER(wt.UINT),
                              ctypes.POINTER(wt.UINT),
                              ctypes.POINTER(RM_PROCESS_INFO),
                              ctypes.POINTER(wt.DWORD)]
    _rm.RmEndSession.argtypes = [wt.DWORD]
except Exception:  # pragma: no cover
    _rm = None


def _exe_of(pid: int) -> str:
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wt.DWORD(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            k32.CloseHandle(h)
    except Exception:
        pass
    return ""


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260),
    ]


def _snapshot() -> dict:
    """{pid: (ppid, name)}，一次遍历拿全，避免逐个查询。"""
    TH32CS_SNAPPROCESS = 0x00000002
    out = {}
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1:
            return out
        try:
            e = PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = k32.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                out[int(e.th32ProcessID)] = (int(e.th32ParentProcessID), e.szExeFile)
                ok = k32.Process32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
    except Exception:
        pass
    return out


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _mem_kb(pid: int) -> int:
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return 0
        try:
            psapi = ctypes.WinDLL("psapi")
            c = PROCESS_MEMORY_COUNTERS()
            c.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            if psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
                return int(c.WorkingSetSize // 1024)
        finally:
            k32.CloseHandle(h)
    except Exception:
        pass
    return 0


def _still_alive(pid: int, start_time) -> bool:
    """PID 会被复用，必须比对创建时间才能确认是同一个进程。"""
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            ct, et, kt, ut = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
            if not k32.GetProcessTimes(h, ctypes.byref(ct), ctypes.byref(et),
                                       ctypes.byref(kt), ctypes.byref(ut)):
                return True     # 查不到就当作还在，宁可多报
            return (ct.dwLowDateTime == start_time.dwLowDateTime
                    and ct.dwHighDateTime == start_time.dwHighDateTime)
        finally:
            k32.CloseHandle(h)
    except Exception:
        return True


GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = ctypes.c_void_p
INVALID_HANDLE = 0xFFFFFFFFFFFFFFFF


def is_locked_file(path: str) -> bool:
    """独占打开测试：能打开说明没被独占锁住。

    这是判定「迁移会不会因为这个文件失败」最直接的办法——
    robocopy 复制的正是这些打不开的文件。比让 Restart Manager
    去猜哪批文件被占用准得多。
    """
    h = _k32.CreateFileW(path, GENERIC_READ, 0, None, OPEN_EXISTING,
                         FILE_ATTRIBUTE_NORMAL, None)
    if not h or h == INVALID_HANDLE:
        err = ctypes.get_last_error()
        return err in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION)
    _k32.CloseHandle(ctypes.c_void_p(h))
    return False


def _top_dirs(root: str) -> list:
    """一级子目录（跳过重解析点）。"""
    out = []
    try:
        with os.scandir(root) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False) and not (
                            e.stat(follow_symlinks=False).st_file_attributes & 0x400):
                        out.append(e.path)
                except OSError:
                    continue
    except OSError:
        pass
    return out


def _files_in(d: str, want: int, max_entries: int = 4000):
    """在单个目录树里取最近修改的 want 个文件（广度优先，条目数有上限）。"""
    from collections import deque
    rows = []
    seen = 0
    q = deque([d])
    while q and seen < max_entries:
        cur = q.popleft()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    seen += 1
                    if seen >= max_entries:
                        break
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if not (e.stat(follow_symlinks=False).st_file_attributes
                                    & 0x400):
                                q.append(e.path)
                        else:
                            rows.append((e.stat(follow_symlinks=False).st_mtime, e.path))
                    except OSError:
                        continue
        except OSError:
            continue
    rows.sort(reverse=True)
    return [p for _, p in rows[:want]]


def _sample_files(root: str, limit: int = 320, max_walk: int = 6000) -> list:
    """挑一批「最可能被占用」的文件。

    旧实现是深度优先 + 单一预算，遇到 binaries 这种两万多个文件的目录时
    预算会被一个子目录吃光，根目录上的 workbuddy.db / lockfile 反而采不到。
    现在改成：根目录下的文件全取，再给每个一级子目录分配配额，保证覆盖。
    """
    picked = []
    try:
        with os.scandir(root) as it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        picked.append((e.stat(follow_symlinks=False).st_mtime, e.path))
                except OSError:
                    continue
    except OSError:
        return []

    tops = _top_dirs(root)
    if tops:
        quota = max(12, min(60, limit // max(1, len(tops))))
        for d in tops:
            for p in _files_in(d, quota, max_entries=max(800, max_walk // max(1, len(tops)))):
                picked.append((0.0, p))     # 已按 mtime 排好，权重置 0 保持稳定
    picked.sort(key=lambda x: x[0], reverse=True)
    out, seen = [], set()
    for _, p in picked:
        k = os.path.normcase(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
        if len(out) >= limit:
            break
    return out


def locked_files(root: str, limit: int = 120, budget: int = 1500) -> list:
    """找出真正被独占锁住的文件，供 Restart Manager 精确定位占用进程。

    只探有限个，保证耗时可控（实测 100 多个文件在 1 秒内）。
    """
    out = []
    for p in _sample_files(root, limit=budget):
        if is_locked_file(p):
            out.append(p)
            if len(out) >= limit:
                break
    return out



def visible_pids() -> set:
    """有可见窗口的进程。用来判断「这个进程用户是不是正在用」。"""
    out = set()
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def cb(hwnd, _):
            try:
                if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                    pid = wt.DWORD(0)
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value:
                        out.add(int(pid.value))
            except Exception:
                pass
            return True

        user32.EnumWindows(cb, 0)
    except Exception:
        pass
    return out


def _ancestor_chain(pid: int, snap: dict, depth: int = 3) -> str:
    """返回「谁把它拉起来的」链条，父在前，例如 cmd.exe ← msedge.exe。"""
    names = []
    cur = snap.get(pid, (0, ""))[0]
    for _ in range(depth):
        if not cur or cur <= 4:
            break
        info = snap.get(cur)
        if not info:
            break
        nm = info[1]
        if nm and nm.lower() not in ("explorer.exe", "winlogon.exe", "services.exe"):
            names.append(nm)
        cur = info[0]
    return " ← ".join(names) if names else "—"


def using_processes(path: str, limit: int = 320, extra_files=None) -> list:
    """返回 [{pid, name, exe, type}]，可能为空（没占用 / 权限不足）。

    extra_files 用于传入「已经确认被独占锁住」的文件——把它们一起注册，
    Restart Manager 才能精准定位到持有者，而不是在一堆没被锁的文件里瞎猜。
    """
    if _rm is None or not os.path.exists(path):
        return []
    files = list(extra_files or [])
    for p in _sample_files(path, limit=limit):
        if p not in files:
            files.append(p)
    if not files:
        return []

    session = wt.DWORD(0)
    key = ctypes.create_unicode_buffer(CCH_RM_SESSION_KEY + 1)
    if _rm.RmStartSession(ctypes.byref(session), 0, key) != ERROR_SUCCESS:
        return []
    try:
        arr = (wt.LPCWSTR * len(files))(*files)
        if _rm.RmRegisterResources(session, len(files), arr, 0, None, 0,
                                   None) != ERROR_SUCCESS:
            return []

        needed = wt.UINT(0)
        count = wt.UINT(0)
        reasons = wt.DWORD(0)
        rc = _rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count),
                           None, ctypes.byref(reasons))
        if rc == ERROR_SUCCESS and needed.value == 0:
            return []
        if rc not in (ERROR_SUCCESS, ERROR_MORE_DATA):
            return []

        n = max(needed.value, 1)
        buf = (RM_PROCESS_INFO * n)()
        count = wt.UINT(n)
        rc = _rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count),
                           buf, ctypes.byref(reasons))
        if rc not in (ERROR_SUCCESS, ERROR_MORE_DATA):
            return []

        out = []
        me = os.getpid()
        snap = _snapshot()
        win_pids = visible_pids()
        for i in range(min(count.value, n)):
            info = buf[i]
            pid = int(info.Process.dwProcessId)
            if pid == me or pid <= 4:
                continue
            # 进程可能已经退出（Restart Manager 拿到的是查询那一刻的快照）
            if not _still_alive(pid, info.Process.ProcessStartTime):
                continue
            exe = _exe_of(pid)
            name = os.path.basename(exe) if exe else (info.strAppName or f"PID {pid}")
            out.append({
                "pid": pid,
                "name": name,
                "exe": exe,
                "app": info.strAppName,
                "type": RM_APP_TYPE.get(int(info.ApplicationType), "未知"),
                "parent": _ancestor_chain(pid, snap),
                "mem_kb": _mem_kb(pid),
                "has_window": pid in win_pids,
            })
        # 去重
        seen, uniq = set(), []
        for p in out:
            if p["pid"] in seen:
                continue
            seen.add(p["pid"])
            uniq.append(p)
        uniq.sort(key=lambda x: x["name"].lower())
        return uniq
    finally:
        try:
            _rm.RmEndSession(session)
        except Exception:
            pass


TASKKILL_DENIED = 5


def _pids_to_keep():
    """绝不能结束的进程：自己和所有祖先（cmd.exe / 父 shell 一杀，本程序跟着崩）。"""
    keep = {os.getpid()}
    try:
        snap = _snapshot()
        cur = os.getpid()
        for _ in range(8):
            ppid = snap.get(cur, (0, ""))[0]
            if not ppid or ppid <= 4 or ppid in keep:
                break
            keep.add(ppid)
            cur = ppid
    except Exception:
        pass
    return keep


def kill_processes(pids) -> tuple:
    """结束进程，返回 (成功数, [(pid, 原因)])。

    用 taskkill /F /T 结束整个进程树：父进程死了子进程还活着，占用照样不释放。
    另外会把自己和自己的祖先进程剔除——否则结束 cmd.exe 会把本程序一起带走，
    表现就是「点了按钮，界面直接消失，什么提示都没有」。
    """
    from .util import run
    keep = _pids_to_keep()
    ok, bad = 0, []
    for pid in pids:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        if pid in keep:
            bad.append((pid, "是本程序或它的父进程，已跳过"))
            continue
        rc, out, err = run(["taskkill", "/F", "/T", "/PID", str(pid)])
        if rc == 0:
            ok += 1
        else:
            why = ((err or "") + (out or "")).strip().splitlines()
            text = why[0].strip() if why else ""
            if not text:
                text = f"taskkill 返回 {rc}"
            bad.append((pid, text[:100]))
    return ok, bad


# 这些进程绝对不允许「一键结束」
PROTECTED = {
    "system", "system idle process", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "smss.exe", "explorer.exe", "dwm.exe",
    "svchost.exe", "fontdrvhost.exe", "ctfmon.exe", "sihost.exe",
    "taskhostw.exe", "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    # 终端/解释器：结束它们会把本程序或它所在的会话一起干掉
    "cmd.exe", "conhost.exe", "windowsterminal.exe", "wt.exe",
    "openconsole.exe", "python.exe", "pythonw.exe", "explorer.exe",
}


def is_protected(name: str) -> bool:
    return (name or "").lower() in PROTECTED
