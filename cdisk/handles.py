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


def _sample_files(root: str, limit: int = 320, max_walk: int = 6000) -> list:
    """挑一批「最可能被占用」的文件：优先最近修改过的。"""
    rows = []
    seen = 0
    stack = [root]
    while stack and seen < max_walk:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    seen += 1
                    if seen >= max_walk:
                        break
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if not (e.stat(follow_symlinks=False).st_file_attributes
                                    & 0x400):  # 跳过重解析点
                                stack.append(e.path)
                        else:
                            st = e.stat(follow_symlinks=False)
                            rows.append((st.st_mtime, e.path))
                    except OSError:
                        continue
        except OSError:
            continue
    rows.sort(reverse=True)
    return [p for _, p in rows[:limit]]


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


def using_processes(path: str, limit: int = 320) -> list:
    """返回 [{pid, name, exe, type}]，可能为空（没占用 / 权限不足）。"""
    if _rm is None or not os.path.exists(path):
        return []
    files = _sample_files(path, limit=limit)
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


def kill_processes(pids) -> tuple:
    """结束进程，返回 (成功数, 失败列表)。"""
    from .util import run
    ok, bad = 0, []
    for pid in pids:
        rc, _, err = run(["taskkill", "/F", "/PID", str(pid)])
        if rc == 0:
            ok += 1
        else:
            bad.append((pid, (err or "").strip()[:80]))
    return ok, bad


# 这些进程绝对不允许「一键结束」
PROTECTED = {
    "system", "system idle process", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "smss.exe", "explorer.exe", "dwm.exe",
    "svchost.exe", "fontdrvhost.exe", "ctfmon.exe", "sihost.exe",
    "taskhostw.exe", "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
}


def is_protected(name: str) -> bool:
    return (name or "").lower() in PROTECTED
