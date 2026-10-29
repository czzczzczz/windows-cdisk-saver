# -*- coding: utf-8 -*-
"""C 盘写入监控：
  1) 实时监听 —— ReadDirectoryChangesW 递归监听指定目录，任何新增/改写立刻上报；
  2) 快照对比 —— 定期给目录拍体积快照，两次对比找出「谁在长胖」。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import queue
import threading
import time

from .util import data_path, load_json, save_json

FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_ALL = 0x00000007
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

FILTER = 0x1 | 0x2 | 0x4 | 0x8 | 0x10 | 0x40   # 名称/属性/大小/写时间/创建

ACT_ADDED = 1
ACT_REMOVED = 2
ACT_MODIFIED = 3
ACT_RENAMED_OLD = 4
ACT_RENAMED_NEW = 5
ACT_LABEL = {1: "新增", 2: "删除", 3: "修改", 4: "改名(旧)", 5: "改名(新)"}

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = ctypes.c_void_p
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                             wt.DWORD, wt.DWORD, ctypes.c_void_p]
_k32.ReadDirectoryChangesW.restype = wt.BOOL
_k32.ReadDirectoryChangesW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                                       wt.BOOL, wt.DWORD, ctypes.POINTER(wt.DWORD),
                                       ctypes.c_void_p, ctypes.c_void_p]
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_k32.CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p]


def _parse(buf, nbytes, base):
    out = []
    off = 0
    while off < nbytes:
        try:
            nxt = ctypes.c_uint32.from_buffer(buf, off).value
            act = ctypes.c_uint32.from_buffer(buf, off + 4).value
            ln = ctypes.c_uint32.from_buffer(buf, off + 8).value
            name = ctypes.wstring_at(ctypes.addressof(buf) + off + 12, ln // 2)
        except Exception:
            break
        out.append((act, os.path.join(base, name)))
        if nxt == 0:
            break
        off += nxt
    return out


class Watcher:
    """多目录递归监听。事件进队列，由 UI 线程 drain。"""

    def __init__(self, on_error=None):
        self.q = queue.Queue(maxsize=50000)
        self._stop = threading.Event()
        self._handles = []
        self._threads = []
        self._lock = threading.Lock()
        self.on_error = on_error
        self.dropped = 0

    def add_root(self, path: str) -> bool:
        if not os.path.isdir(path):
            return False
        h = _k32.CreateFileW(path, FILE_LIST_DIRECTORY, FILE_SHARE_ALL, None,
                             OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, None)
        if not h or h == INVALID_HANDLE_VALUE:
            if self.on_error:
                self.on_error(f"无法监听 {path}（可能需要管理员权限）")
            return False
        with self._lock:
            self._handles.append(h)
        t = threading.Thread(target=self._loop, args=(h, path), daemon=True)
        t.start()
        self._threads.append(t)
        return True

    def _loop(self, h, base):
        buf = ctypes.create_string_buffer(64 * 1024)
        ret = wt.DWORD(0)
        while not self._stop.is_set():
            ok = _k32.ReadDirectoryChangesW(h, buf, len(buf), True, FILTER,
                                            ctypes.byref(ret), None, None)
            if not ok or self._stop.is_set():
                err = ctypes.get_last_error()
                if not self._stop.is_set() and err == 1223:
                    continue
                break
            n = ret.value
            if n == 0:
                # 缓冲区溢出，事件被丢弃
                self.dropped += 1
                continue
            for act, p in _parse(buf, n, base):
                if act in (ACT_REMOVED, ACT_RENAMED_OLD):
                    continue
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    sz = 0
                item = {"t": time.time(), "act": act, "path": p, "size": sz}
                try:
                    self.q.put_nowait(item)
                except queue.Full:
                    try:
                        self.q.get_nowait()
                    except queue.Empty:
                        pass
                    self.dropped += 1

    def stop(self):
        self._stop.set()
        with self._lock:
            for h in self._handles:
                try:
                    _k32.CancelIoEx(h, None)
                    _k32.CloseHandle(h)
                except Exception:
                    pass
            self._handles.clear()

    def drain(self, limit=400):
        out = []
        for _ in range(limit):
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                break
        return out


# ------------------------------------------------------------------ 快照对比
SNAP_FILE = data_path("snapshots.json")


def default_roots() -> list:
    u = os.environ.get("USERPROFILE", "")
    roots = [u, os.path.join(u, "AppData", "Local"), os.path.join(u, "AppData", "Roaming")]
    extra = [os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
             os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Temp"),
             os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                          "SoftwareDistribution", "Download")]
    for e in extra:
        if e and os.path.isdir(e):
            roots.append(e)
    return [r for r in dict.fromkeys(roots) if r and os.path.isdir(r)]


def take_snapshot(roots=None, max_depth=2, progress=None, cancel=None) -> dict:
    """返回 {path: [size, files]}，目录粒度默认两层。"""
    from .scan import flatten, scan
    roots = roots or default_roots()
    out = {}
    for r in roots:
        if cancel is not None and cancel.is_set():
            break
        node, _ = scan(r, max_depth=max_depth, big_limit=0, big_min=1 << 62,
                       progress=progress, cancel=cancel)
        flatten(node, out)
    return out


def save_snapshot(data: dict) -> dict:
    snaps = load_json(SNAP_FILE, {"items": []}).get("items", [])
    rec = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "data": data}
    snaps.insert(0, rec)
    save_json(SNAP_FILE, {"items": snaps[:8]})
    return rec


def load_snapshots() -> list:
    return load_json(SNAP_FILE, {"items": []}).get("items", [])


def diff_snapshots(old: dict, new: dict, top: int = 80) -> list:
    """返回 [(delta_bytes, path, old_size, new_size)]，按增长降序。"""
    keys = set(old) | set(new)
    rows = []
    for k in keys:
        o = old.get(k, [0, 0])[0]
        n = new.get(k, [0, 0])[0]
        d = n - o
        if d != 0:
            rows.append((d, k, o, n))
    rows.sort(reverse=True)
    grown = [r for r in rows if r[0] > 0][:top]
    shrunk = [r for r in rows if r[0] < 0][:20]
    return grown, shrunk
