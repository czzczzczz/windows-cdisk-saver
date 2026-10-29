# -*- coding: utf-8 -*-
"""端到端自检：真实执行一次 迁移 → 校验 → 还原，确认引擎可用。"""
from __future__ import annotations

import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cdisk.migrate import Job, migrate_job, rollback          # noqa: E402
from cdisk.scan import scan                                    # noqa: E402
from cdisk.targets import Target                               # noqa: E402
from cdisk.util import dir_stats, free_bytes, human, is_admin, is_junction  # noqa: E402

HOME = os.environ["USERPROFILE"]
SRC = os.path.join(HOME, "_cdisk_selftest_src")
DST_ROOT = r"D:\CDiskSaver_selftest"


def make_files(root, n=60):
    os.makedirs(root, exist_ok=True)
    for i in range(n):
        sub = os.path.join(root, "sub%d" % (i % 4))
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, "f%03d.bin" % i), "wb") as f:
            f.write(os.urandom(4096 * (1 + i % 7)))


def main():
    print("=" * 66)
    print("C 盘空间管家 · 引擎自检")
    print("=" * 66)
    print(f"管理员权限 : {is_admin()}")

    # 清理上次残留
    if os.path.exists(SRC):
        if is_junction(SRC):
            os.system(f'cmd /c rmdir "{SRC}"')
        else:
            shutil.rmtree(SRC, ignore_errors=True)
    if os.path.exists(DST_ROOT):
        shutil.rmtree(DST_ROOT, ignore_errors=True)

    make_files(SRC, 60)
    files, size = dir_stats(SRC)
    print(f"[1] 造数据   : {SRC}")
    print(f"    {files} 个文件 / {human(size)}")
    assert files == 60 and size > 0

    dst = os.path.join(DST_ROOT, "selftest")
    job = Job(src=SRC, dst=dst, tid="selftest", name="自检目录").scan()
    print(f"[2] 计划     : {job.src} -> {job.dst}")

    t0 = time.time()
    ok, msg, rec = migrate_job(job, progress=lambda p: None,
                               stage=lambda m: print("    ·", m))
    print(f"[3] 迁移     : ok={ok} {msg}  用时 {time.time()-t0:.1f}s")
    assert ok, msg
    assert is_junction(SRC), "源目录未变成目录联接"
    assert os.path.isdir(dst), "目标目录不存在"

    # 通过原路径仍能读到文件
    probe = os.path.join(SRC, "sub0", "f000.bin")
    assert os.path.exists(probe), "联接后原路径不可读"
    print(f"[4] 联接校验 : 原路径可读 -> {probe} ({os.path.getsize(probe)} B)")
    assert dir_stats(SRC)[0] == 0, "联接被重复统计（会导致空间分析失真）"

    # 体积扫描（真实 C 盘）
    node, big = scan(SRC, max_depth=2)
    print(f"[5] 体积扫描 : {human(node.size)} / {node.files} 文件 / {len(node.children)} 子目录")
    assert node.files == 60

    # 还原
    print("[6] 还原     :", end=" ")
    ok2, msg2 = rollback(rec, stage=lambda m: None)
    print(f"ok={ok2} {msg2}")
    assert ok2, msg2
    assert not is_junction(SRC), "还原后仍是联接"
    assert not os.path.exists(dst), "还原后 D 盘副本未清理"
    f2, s2 = dir_stats(SRC)
    print(f"[7] 数据校验 : {f2} 个文件 / {human(s2)}（原始 {files} / {human(size)}）")
    assert f2 == files and s2 == size, "还原后文件不一致"

    # 清理
    shutil.rmtree(SRC, ignore_errors=True)
    shutil.rmtree(DST_ROOT, ignore_errors=True)
    print("-" * 66)

    test_edge_like()
    print("-" * 66)
    print("全部通过 ✔  迁移 / 联接 / 扫描 / 还原 均正常")
    free_c = human(free_bytes("C:\\"))
    print(f"C 盘可用空间：{free_c}")


def test_edge_like():
    """模拟 Edge 的多配置文件缓存目录：验证「一个目标 → 多个子目录」的映射与迁移。"""
    from cdisk.migrate import build_jobs

    base = os.path.join(HOME, "_cdisk_selftest_edge", "User Data")
    for prof in ("Default", "Profile 1"):
        for sub in ("Cache", "Code Cache"):
            d = os.path.join(base, prof, sub)
            os.makedirs(d, exist_ok=True)
            for i in range(8):
                with open(os.path.join(d, f"data_{i}.tmp"), "wb") as f:
                    f.write(os.urandom(2048))

    t = Target(
        id="edge_like", name="模拟 Edge 缓存", cat="测试",
        paths=[os.path.join(base, "*", "Cache"), os.path.join(base, "*", "Code Cache")],
        base=base,
    )
    dst_root = os.path.join(DST_ROOT, "edge_like_root")
    jobs = build_jobs(t, dst_root)
    print(f"[8] 目标展开 : 找到 {len(jobs)} 个缓存子目录")
    assert len(jobs) == 4, f"应展开 4 个目录，实际 {len(jobs)}"
    for j in jobs:
        rel = os.path.relpath(j.src, base)
        rel_dst = os.path.relpath(j.dst, dst_root)
        print(f"    {rel:22} -> {rel_dst}")
        assert rel_dst.startswith(os.path.join("edge_like", rel.split(os.sep)[0])), \
            "目标路径映射错误"

    recs = []
    for j in jobs:
        j.scan()
        ok, msg, rec = migrate_job(j)
        assert ok, msg
        assert is_junction(j.src)
        recs.append(rec)
    print(f"[9] 批量迁移 : {len(recs)} 个目录全部建立联接")

    # 通过原路径写入，实际落到 D 盘
    probe_dir = os.path.join(base, "Default", "Cache")
    with open(os.path.join(probe_dir, "after_link.txt"), "w") as f:
        f.write("hello")
    landed = os.path.join(dst_root, "edge_like", "Default", "Cache", "after_link.txt")
    assert os.path.exists(landed), "通过原路径写入的文件没有落到 D 盘"
    print(f"[10] 透明性  : 往原路径写文件，实际落在 {os.path.relpath(landed, DST_ROOT)}")

    for rec in recs:
        ok, msg = rollback(rec)
        assert ok, msg
        assert not is_junction(rec["src"])
    print("[11] 全部还原: 4 个目录已搬回 C 盘，联接已删除")

    shutil.rmtree(os.path.join(HOME, "_cdisk_selftest_edge"), ignore_errors=True)
    shutil.rmtree(DST_ROOT, ignore_errors=True)


if __name__ == "__main__":
    main()
