# -*- coding: utf-8 -*-
"""智能发现：扫出用户目录下体积大、但不在内置目标库里的目录。

内置的 33 个目标永远不可能覆盖全部软件，所以必须能自己发现「谁在偷偷占地方」。
"""
from __future__ import annotations

import os

from .scan import scan
from .targets import TARGETS, norm
from .util import reparse_tag

MIN_SIZE = 200 * 1024 * 1024        # 只关心 200 MB 以上的
MAX_ITEMS = 20

# 这些目录即使很大也不该「迁移」，而应该清理
_SKIP_EXACT = {
    r"%userprofile%\appdata\local\temp",
    r"%userprofile%\appdata\local\microsoft\windows\explorer",
    r"%userprofile%\appdata\local\microsoft\windows\inetcache",
    r"%userprofile%\appdata\local\crashdumps",
}

# 这些是「已安装的程序」或「个人文件」，当成迁移建议会误导人，直接不列
_SKIP_PREFIX = (
    r"%userprofile%\appdata\local\programs",      # 用户级安装目录
    r"%userprofile%\appdata\roaming\npm",         # npm 全局包
    r"%userprofile%\appdata\local\microsoft",
    r"%userprofile%\appdata\roaming\microsoft",
    r"%userprofile%\appdata\local\packages",      # UWP 应用数据
    r"%userprofile%\desktop",
    r"%userprofile%\documents",
    r"%userprofile%\pictures",
    r"%userprofile%\videos",
    r"%userprofile%\music",
    r"%userprofile%\favorites",
    r"%userprofile%\links",
    r"%userprofile%\saved games",
    r"%userprofile%\.workbuddy\binaries",         # 运行时本体，正在用
)

# 名字里带这些词的，基本是可重建的缓存/日志，迁移风险低
_SAFE_HINTS = ("cache", "caches", "logs", "\\log", "traces", "tmp", "temp",
               "updater", "crash", "dump", "update", "download")


def _expand(p: str) -> str:
    return os.path.normcase(os.path.expandvars(p))


def _risk(path: str) -> str:
    low = path.lower()
    return "safe" if any(h in low for h in _SAFE_HINTS) else "caution"


def _builtin_bases():
    """内置目标涉及的目录（glob 取 * 之前的固定前缀），用于去重。"""
    out = []
    for t in TARGETS:
        for p in t.paths:
            base = norm(p).replace("/", "\\")
            star = base.find("*")
            if star >= 0:
                base = base[:star].rstrip("\\")
            out.append(os.path.normcase(base))
    return out


def _covered(path: str, bases) -> bool:
    lp = os.path.normcase(path)
    for b in bases:
        # 这个目录本身就是内置目标，或它在内置目标内部
        if lp == b or lp.startswith(b + "\\"):
            return True
        # 内置目标在这个目录内部（说明这个目录已被内置规则覆盖）
        if b.startswith(lp + "\\"):
            return True
    return False


def _skip(path: str) -> bool:
    lp = _expand(path)
    for s in _SKIP_EXACT:
        if lp == _expand(s):
            return True
    for s in _SKIP_PREFIX:
        base = _expand(s)
        if lp == base or lp.startswith(base + "\\"):
            return True
    low = lp.lower()
    if "onedrive" in low:
        return True
    if low.endswith("\\appdata\\local\\microsoft\\windows\\explorer"):
        return True
    return False


def _pick(node, min_size, out=None):
    """只保留「最具体」的合格目录：子目录合格就往下钻，不重复报父目录。"""
    if out is None:
        out = []
    if node.size < min_size:
        return out
    kids = [c for c in node.children if c.size >= min_size]
    if not kids:
        if node.depth >= 1:
            out.append(node)
        return out
    for c in kids:
        _pick(c, min_size, out)
    return out


def discover(progress=None, cancel=None, min_size=MIN_SIZE, max_depth=3):
    """返回 [{path, size, files}]，按体积降序。"""
    home = os.environ.get("USERPROFILE")
    if not home or not os.path.isdir(home):
        return []
    node, _ = scan(home, max_depth=max_depth, big_limit=0, big_min=1 << 62,
                   progress=progress, cancel=cancel)
    bases = _builtin_bases()
    rows = []
    for n in _pick(node, min_size):
        if cancel is not None and cancel.is_set():
            break
        if _skip(n.path) or _covered(n.path, bases) or reparse_tag(n.path):
            continue
        rows.append({"path": n.path, "size": n.size, "files": n.files,
                     "risk": _risk(n.path)})
    rows.sort(key=lambda r: r["size"], reverse=True)
    return rows[:MAX_ITEMS]
