# -*- coding: utf-8 -*-
"""目录体积扫描：生成可展开的目录树 + 大文件排行。

一次遍历同时算出「前 N 层目录的体积」和「超大文件列表」，
遇到 junction / symlink 直接跳过，避免重复统计与死循环。
"""
from __future__ import annotations

import heapq
import os

from .util import human, reparse_tag

SKIP_NAMES = {
    "$recycle.bin", "system volume information", "$windows.~bt", "$windows.~ws",
    "config.msi", "recovery", "windowsapps",
}


class Node:
    __slots__ = ("path", "name", "size", "files", "depth", "children", "parent")

    def __init__(self, path, name, depth, parent=None):
        self.path = path
        self.name = name
        self.size = 0
        self.files = 0
        self.depth = depth
        self.children = []
        self.parent = parent

    def to_dict(self):
        return {
            "name": self.name, "path": self.path, "size": self.size,
            "files": self.files,
            "children": [c.to_dict() for c in self.children],
        }


def scan(root: str, max_depth: int = 3, big_limit: int = 60,
         big_min: int = 80 * 1024 * 1024, progress=None, cancel=None,
         skip_names=None):
    """返回 (root_node, big_files)。big_files = [(size, path), ...] 降序。"""
    root = os.path.normpath(os.path.abspath(root))
    skip_names = skip_names or SKIP_NAMES
    root_node = Node(root, os.path.basename(root) or root, 0)
    nodes = {os.path.normcase(root): root_node}
    big = []
    seen = 0
    last_report = 0

    stack = [(root, 0, root_node)]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        cur, depth, owner = stack.pop()
        try:
            with os.scandir(cur) as it:
                entries = list(it)
        except OSError:
            continue

        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if reparse_tag(e.path):
                        continue
                    if e.name.lower() in skip_names:
                        continue
                    if depth < max_depth:
                        child = Node(e.path, e.name, depth + 1, owner)
                        owner.children.append(child)
                        nodes[os.path.normcase(e.path)] = child
                        stack.append((e.path, depth + 1, child))
                    else:
                        stack.append((e.path, depth + 1, owner))
                else:
                    sz = e.stat(follow_symlinks=False).st_size
                    owner.size += sz
                    owner.files += 1
                    if sz >= big_min:
                        if len(big) < big_limit:
                            heapq.heappush(big, (sz, e.path))
                        elif sz > big[0][0]:
                            heapq.heapreplace(big, (sz, e.path))
                    seen += 1
                    if progress and seen - last_report >= 4000:
                        last_report = seen
                        progress(seen, e.path)
            except OSError:
                continue

    # 自底向上汇总（子目录体积计入父目录）
    def rollup(n):
        for c in n.children:
            rollup(c)
            n.size += c.size
            n.files += c.files

    rollup(root_node)
    root_node.children.sort(key=lambda x: x.size, reverse=True)
    big.sort(reverse=True)
    return root_node, big


def flatten(node, out=None, min_size=0):
    """把树压平成 {path: (size, files)}，用于快照对比。"""
    if out is None:
        out = {}
    if node.size >= min_size:
        out[node.path] = (node.size, node.files)
    for c in node.children:
        flatten(c, out, min_size)
    return out


def find_node(node, path):
    key = os.path.normcase(os.path.normpath(path))
    if os.path.normcase(node.path) == key:
        return node
    for c in node.children:
        r = find_node(c, path)
        if r:
            return r
    return None
