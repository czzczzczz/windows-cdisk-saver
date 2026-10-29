# -*- coding: utf-8 -*-
"""业务服务层：配置、目标扫描结果缓存。"""
from __future__ import annotations

import os

from .migrate import find_record_by_src, load_records
from .targets import TARGETS, default_dest_root
from .util import data_path, dir_stats, human, is_junction, load_json, reparse_tag, save_json

CONFIG = data_path("config.json")


class Service:
    def __init__(self):
        cfg = load_json(CONFIG, {})
        self.dest_root = cfg.get("dest_root") or default_dest_root()
        self.keep_backup = bool(cfg.get("keep_backup", False))
        self.watch_roots = cfg.get("watch_roots") or []
        self.scan_roots = cfg.get("scan_roots") or []
        self.tinfo = []
        self.discovered = []
        self.scanned = False
        self.discovering = False

    def save(self):
        save_json(CONFIG, {
            "dest_root": self.dest_root,
            "keep_backup": self.keep_backup,
            "watch_roots": self.watch_roots,
            "scan_roots": self.scan_roots,
        })

    # -------------------------------------------------------------- 目标扫描
    def scan_targets(self, progress=None, cancel=None):
        rows = []
        for t in TARGETS:
            if progress:
                progress(f"正在统计：{t.name}")
            if t.kind == "manual":
                rows.append({"t": t, "dirs": [], "size": 0, "state": "manual", "dst": ""})
                continue
            dirs = t.expand()
            if not dirs:
                rows.append({"t": t, "dirs": [], "size": 0, "state": "none", "dst": ""})
                continue
            total = 0
            for d in dirs:
                if cancel is not None and cancel.is_set():
                    break
                if reparse_tag(d):
                    rec = find_record_by_src(d)
                    if rec:
                        total += rec.get("bytes", 0)
                    else:
                        try:
                            total += dir_stats(d, skip_links=False)[1]
                        except Exception:
                            pass
                else:
                    total += dir_stats(d)[1]
            state = t.state(self.dest_root)
            dst = t.dest_for(dirs[0], self.dest_root) if dirs else ""
            rows.append({"t": t, "dirs": dirs, "size": total, "state": state, "dst": dst})
        self.tinfo = rows
        self.scanned = True
        return rows

    def row(self, tid):
        for r in self.tinfo:
            if r["t"].id == tid:
                return r
        return None

    # -------------------------------------------------------------- 智能发现
    def discover_big(self, progress=None, cancel=None):
        """扫出内置目标库之外的占空间大户。"""
        from .discover import discover
        self.discovering = True
        try:
            self.discovered = discover(progress=progress, cancel=cancel)
        finally:
            self.discovering = False
        return self.discovered

    def discovered_bytes(self) -> int:
        return sum(r["size"] for r in self.discovered)

    # -------------------------------------------------------------- 汇总
    def migratable_bytes(self) -> int:
        return sum(r["size"] for r in self.tinfo if r["state"] in ("ok", "part"))

    def moved_bytes(self) -> int:
        return sum(x.get("bytes", 0) for x in load_records() if x.get("status") == "done")

    def summary(self) -> str:
        total = self.migratable_bytes()
        return human(total)
