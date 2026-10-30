# -*- coding: utf-8 -*-
"""迁移引擎：robocopy 复制 → 校验 → 改名占位 → 建立目录联接(Junction) → 释放源目录。

设计原则：
  * 任何一步失败都回退到「源目录原样」，不留半成品；
  * 全过程写入 journal.json，可一键还原；
  * 不使用符号链接（需要开发者模式），统一用目录联接，普通管理员即可。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass

from .util import (
    CREATE_NO_WINDOW, data_path, dir_stats, drive_of, free_bytes, is_junction,
    load_json, norm, popen_quiet, reparse_tag, rmtree_force, run, save_json,
)

JOURNAL = data_path("journal.json")
BAK_SUFFIX = ".__cdisk_bak"


# ------------------------------------------------------------------ 底层操作
def make_junction(link: str, target: str) -> bool:
    rc, out, err = run(["cmd", "/c", "mklink", "/J", link, target])
    return rc == 0 and os.path.exists(link)


def remove_junction(link: str) -> bool:
    """只删除联接本身，不会删到目标内容。"""
    if not is_junction(link):
        return False
    run(["cmd", "/c", "rmdir", link])
    return not os.path.exists(link)


def set_user_env(name: str, value: str) -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x001A, 0, "Environment")
        return True
    except Exception:
        return False


def _robocopy(src: str, dst: str, total: int, progress=None, cancel=None):
    """复制目录，进度用目标盘剩余空间反推（O(1)，不遍历文件树）。"""
    os.makedirs(dst, exist_ok=True)
    args = ["robocopy", src, dst, "/E", "/COPY:DAT", "/DCOPY:DAT",
            "/R:2", "/W:2", "/MT:16", "/XJ", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"]
    free0 = free_bytes(dst)
    p = popen_quiet(args)
    while p.poll() is None:
        if cancel is not None and cancel.is_set():
            p.kill()
            return False, "用户取消"
        if progress and total > 0:
            used = max(0, free0 - free_bytes(dst))
            progress(min(used / float(total), 0.985))
        time.sleep(0.8)
    rc = p.returncode
    if progress:
        progress(1.0)
    if rc >= 8:
        return False, f"robocopy 失败 (code={rc})"
    return True, ""


def _delete_tree(path: str, total_files: int = 0, progress=None):
    """删除源目录（迁移成功后的空间释放）。"""
    if progress:
        progress(0.0)
    ok = rmtree_force(path)
    if progress:
        progress(1.0)
    return ok


# ------------------------------------------------------------------ 数据模型
@dataclass
class Job:
    src: str
    dst: str
    files: int = 0
    bytes: int = 0
    env: tuple = ()
    tid: str = ""
    name: str = ""

    def scan(self):
        self.files, self.bytes = dir_stats(self.src)
        return self


# ------------------------------------------------------------------ 主流程
def build_jobs(target, dest_root: str) -> list:
    jobs = []
    for src in target.expand():
        dst = target.dest_for(src, dest_root)
        jobs.append(Job(src=src, dst=dst, tid=target.id, name=target.name))
    return jobs


def migrate_job(job: Job, progress=None, stage=None, cancel=None,
                keep_backup: bool = False):
    """执行单个迁移。返回 (ok, message, record|None)。

    progress(0~1) 用于进度条，stage(text) 用于状态文字。
    """
    def st(msg):
        if stage:
            stage(msg)

    src, dst = job.src, job.dst
    if not os.path.isdir(src):
        return False, "源目录不存在", None
    if reparse_tag(src):
        return False, "源目录已经是链接，无需迁移", None
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
        return False, "源目录与目标目录相同", None
    if drive_of(src) == drive_of(dst):
        return False, "目标目录必须位于另一个磁盘分区", None
    if os.path.exists(dst) and os.listdir(dst):
        return (False,
                f"目标目录已存在且非空，未做任何改动。\n"
                f"  {dst}\n"
                f"可能是上次迁移的残留。请先删掉该目录，或换一个落点再试。", None)

    if job.files == 0 and job.bytes == 0:
        job.scan()
    total = job.bytes

    # 1. 复制
    st(f"正在复制到 {dst} …")
    ok, err = _robocopy(src, dst, total, progress, cancel)
    if not ok:
        _delete_tree(dst)
        return False, err, None

    # 2. 校验
    st("正在校验文件数量与大小 …")
    d_files, d_bytes = dir_stats(dst)
    if d_files != job.files or abs(d_bytes - job.bytes) > max(4096, total // 10000):
        _delete_tree(dst)
        return False, f"校验不一致：源 {job.files} 个/{job.bytes} B，目标 {d_files} 个/{d_bytes} B", None

    # 3. 让位 + 建立联接
    st("正在建立目录联接 …")
    bak = src + BAK_SUFFIX
    if os.path.exists(bak):
        rmtree_force(bak)
    try:
        os.rename(src, bak)
    except OSError as exc:
        _delete_tree(dst)
        if getattr(exc, "winerror", None) == 5:
            return (False,
                    "源目录被占用或权限不足（WinError 5）：有程序正在使用其中的文件，"
                    "或当前账户无权修改该目录。请关闭相关程序，或以管理员身份运行后重试。",
                    None)
        return False, f"源目录被占用，请先关闭相关程序：{exc}", None

    if not make_junction(src, dst):
        os.rename(bak, src)
        _delete_tree(dst)
        return False, "创建目录联接失败（请以管理员身份运行）", None

    if not (is_junction(src) and os.path.isdir(src)):
        remove_junction(src)
        os.rename(bak, src)
        _delete_tree(dst)
        return False, "目录联接校验失败，已回退", None

    # 4. 释放源目录
    if keep_backup:
        st(f"已保留备份：{bak}")
    else:
        st("正在释放 C 盘空间 …")
        if progress:
            progress(0.0)
        rmtree_force(bak)
        if progress:
            progress(1.0)

    # 5. 环境变量（可选）
    for name, tpl in (job.env or ()):
        set_user_env(name, tpl.format(dst=dst))

    rec = {
        "id": uuid.uuid4().hex[:12],
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tid": job.tid,
        "name": job.name or os.path.basename(src),
        "src": src,
        "dst": dst,
        "files": job.files,
        "bytes": job.bytes,
        "backup": bak if keep_backup else "",
        "status": "done",
    }
    add_record(rec)
    return True, f"完成，已释放 {job.bytes/1024/1024/1024:.2f} GB", rec


def rollback(rec: dict, progress=None, stage=None) -> tuple:
    """把已迁移的目录搬回 C 盘并删除联接。"""
    def st(msg):
        if stage:
            stage(msg)

    src, dst = rec["src"], rec["dst"]
    if not is_junction(src):
        return False, "源路径不是联接，无法自动还原"
    if not os.path.isdir(dst):
        return False, f"目标目录丢失：{dst}"

    st("正在移除目录联接 …")
    if not remove_junction(src):
        return False, "移除联接失败"

    st("正在把数据搬回 C 盘 …")
    total = rec.get("bytes", 0)
    ok, err = _robocopy(dst, src, total, progress, None)
    if not ok:
        make_junction(src, dst)
        return False, f"还原复制失败：{err}"

    st("正在清理 D 盘副本 …")
    rmtree_force(dst)
    rec["status"] = "rolledback"
    update_record(rec)
    return True, "已还原到 C 盘"


# ------------------------------------------------------------------ 台账
def load_records() -> list:
    data = load_json(JOURNAL, {"records": []})
    return data.get("records", [])


def _save_records(recs: list):
    save_json(JOURNAL, {"records": recs})


def add_record(rec: dict):
    recs = load_records()
    recs.insert(0, rec)
    _save_records(recs[:500])


def update_record(rec: dict):
    recs = load_records()
    for i, r in enumerate(recs):
        if r.get("id") == rec.get("id"):
            recs[i] = rec
            break
    _save_records(recs)


def find_record_by_src(src: str):
    for r in load_records():
        if os.path.normcase(r.get("src", "")) == os.path.normcase(src):
            return r
    return None
