# -*- coding: utf-8 -*-
"""内置可迁移目标库：常见软件的缓存 / 数据目录，以及迁移到 D 盘的默认落点。"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field

from .util import norm, is_junction, reparse_tag

U = "%USERPROFILE%"
LA = "%LOCALAPPDATA%"
AD = "%APPDATA%"
DOC = "%USERPROFILE%\\Documents"


@dataclass
class Target:
    id: str
    name: str
    cat: str
    paths: list = field(default_factory=list)
    base: str = ""
    desc: str = ""
    risk: str = "safe"          # safe | caution | manual
    kind: str = "junction"      # junction | manual
    env: tuple = ()             # ((变量名, 目标值模板), ...)
    procs: tuple = ()           # 迁移前建议关闭的进程
    admin: bool = False
    manual: str = ""            # kind=manual 时的操作说明
    tags: tuple = ()

    # ---------------------------------------------------------- 展开实际路径
    def expand(self) -> list:
        out = []
        seen = set()
        for p in self.paths:
            pat = norm(p)
            hits = glob.glob(pat) if any(c in pat for c in "*?[") else (
                [pat] if os.path.exists(pat) else [])
            for h in hits:
                if not os.path.isdir(h):
                    continue
                k = os.path.normcase(os.path.abspath(h))
                if k in seen:
                    continue
                seen.add(k)
                out.append(os.path.abspath(h))
        return out

    def dest_for(self, src: str, dest_root: str) -> str:
        base = norm(self.base) if self.base else ""
        rel = ""
        if base and os.path.normcase(src).startswith(os.path.normcase(base)):
            rel = src[len(base):].strip("\\/")
        if not rel:
            rel = os.path.basename(src.rstrip("\\/")) or self.id
        return os.path.join(dest_root, self.id, rel)

    def state(self, dest_root: str = "") -> str:
        """none=未安装  ok=可迁移  done=已迁移  link=已是链接"""
        dirs = self.expand()
        if not dirs:
            return "none"
        flags = [reparse_tag(d) for d in dirs]
        if all(flags):
            return "done"
        if any(flags):
            return "part"
        return "ok"


TARGETS: list = [
    # ---------------------------------------------------------------- 聊天办公
    Target("wechat4_files", "微信 4.x 聊天文件", "聊天办公",
           [DOC + "\\xwechat_files"], DOC + "\\xwechat_files",
           "微信 4.x 接收的图片、视频、文件，动辄几十 GB，迁移后微信完全无感。",
           "caution", procs=("Weixin.exe", "WeChat.exe")),
    Target("wechat3_files", "微信 3.x 聊天记录", "聊天办公",
           [DOC + "\\WeChat Files"], DOC + "\\WeChat Files",
           "老版微信的聊天记录与文件目录。", "caution",
           procs=("WeChat.exe",)),
    Target("qq_files", "QQ / TIM 聊天文件", "聊天办公",
           [DOC + "\\Tencent Files", DOC + "\\Tencent Files*"], DOC + "\\Tencent Files",
           "QQ NT、TIM 的聊天文件、图片、语音缓存。", "caution",
           procs=("QQ.exe", "TIM.exe")),
    Target("wxwork", "企业微信 文件缓存", "聊天办公",
           [DOC + "\\WXWork"], DOC + "\\WXWork",
           "企业微信的聊天文件与图片缓存。", "caution", procs=("WXWork.exe",)),
    Target("dingtalk", "钉钉 文件缓存", "聊天办公",
           [DOC + "\\DingTalk", LA + "\\DingTalk\\media_cache"], "",
           "钉钉接收的文件与媒体缓存。", "caution", procs=("DingTalk.exe",)),

    # ---------------------------------------------------------------- 浏览器
    Target("edge_cache", "Edge 浏览器缓存", "浏览器",
           [LA + "\\Microsoft\\Edge\\User Data\\*\\Cache",
            LA + "\\Microsoft\\Edge\\User Data\\*\\Code Cache",
            LA + "\\Microsoft\\Edge\\User Data\\*\\GPUCache",
            LA + "\\Microsoft\\Edge\\User Data\\*\\DawnGraphiteCache",
            LA + "\\Microsoft\\Edge\\User Data\\*\\DawnWebGPUCache",
            LA + "\\Microsoft\\Edge\\User Data\\*\\GrShaderCache",
            LA + "\\Microsoft\\Edge\\User Data\\*\\ShaderCache",
            LA + "\\Microsoft\\Edge\\User Data\\*\\Service Worker\\CacheStorage"],
           LA + "\\Microsoft\\Edge\\User Data",
           "各配置文件的网页缓存、代码缓存、GPU 缓存。不含书签和密码。",
           "safe", procs=("msedge.exe",)),
    Target("chrome_cache", "Chrome 浏览器缓存", "浏览器",
           [LA + "\\Google\\Chrome\\User Data\\*\\Cache",
            LA + "\\Google\\Chrome\\User Data\\*\\Code Cache",
            LA + "\\Google\\Chrome\\User Data\\*\\GPUCache",
            LA + "\\Google\\Chrome\\User Data\\*\\GrShaderCache",
            LA + "\\Google\\Chrome\\User Data\\*\\ShaderCache",
            LA + "\\Google\\Chrome\\User Data\\*\\Service Worker\\CacheStorage"],
           LA + "\\Google\\Chrome\\User Data",
           "Chrome 的网页缓存目录，迁移不影响登录状态与书签。",
           "safe", procs=("chrome.exe",)),
    Target("firefox_cache", "Firefox 浏览器缓存", "浏览器",
           [LA + "\\Mozilla\\Firefox\\Profiles\\*\\cache2"],
           LA + "\\Mozilla\\Firefox\\Profiles",
           "Firefox 的磁盘缓存。", "safe", procs=("firefox.exe",)),

    # ---------------------------------------------------------------- 开发环境
    Target("pip_cache", "pip 安装包缓存", "开发环境",
           [LA + "\\pip\\Cache"], LA + "\\pip\\Cache",
           "pip 下载过的 wheel 缓存，重装依赖时能离线复用。", "safe",
           env=(("PIP_CACHE_DIR", "{dst}"),)),
    Target("npm_cache", "npm 包缓存", "开发环境",
           [LA + "\\npm-cache", AD + "\\npm-cache"], "",
           "npm 的 _cacache 缓存，通常几 GB。", "safe",
           env=(("npm_config_cache", "{dst}"),)),
    Target("yarn_cache", "yarn 包缓存", "开发环境",
           [LA + "\\Yarn\\Cache"], LA + "\\Yarn\\Cache",
           "yarn 全局缓存。", "safe", env=(("YARN_CACHE_FOLDER", "{dst}"),)),
    Target("pnpm_store", "pnpm 包仓库", "开发环境",
           [LA + "\\pnpm\\store", LA + "\\pnpm-store"], "",
           "pnpm 内容寻址仓库，体积通常很大。", "safe"),
    Target("cargo", "Rust Cargo 目录", "开发环境",
           [U + "\\.cargo"], U + "\\.cargo",
           "crates 缓存与已编译产物。", "safe", env=(("CARGO_HOME", "{dst}"),)),
    Target("rustup", "Rust 工具链", "开发环境",
           [U + "\\.rustup"], U + "\\.rustup",
           "Rust 各版本工具链，单个 toolchain 约 1.5 GB。", "safe",
           env=(("RUSTUP_HOME", "{dst}"),)),
    Target("go_mod", "Go 模块缓存", "开发环境",
           [U + "\\go\\pkg\\mod"], U + "\\go\\pkg\\mod",
           "GOPATH 下的模块缓存。", "safe", env=(("GOMODCACHE", "{dst}"),)),
    Target("go_build", "Go 编译缓存", "开发环境",
           [LA + "\\go-build"], LA + "\\go-build",
           "go build 的中间产物缓存。", "safe", env=(("GOCACHE", "{dst}"),)),
    Target("gradle", "Gradle 用户目录", "开发环境",
           [U + "\\.gradle"], U + "\\.gradle",
           "依赖与构建缓存，Android 开发常占 5-20 GB。", "safe",
           env=(("GRADLE_USER_HOME", "{dst}"),)),
    Target("maven", "Maven 本地仓库", "开发环境",
           [U + "\\.m2\\repository"], U + "\\.m2\\repository",
           "Maven 下载的 jar 仓库。", "safe"),
    Target("nuget", "NuGet 包缓存", "开发环境",
           [U + "\\.nuget\\packages"], U + "\\.nuget\\packages",
           ".NET 项目依赖包。", "safe", env=(("NUGET_PACKAGES", "{dst}"),)),
    Target("conda_pkgs", "Conda 包缓存", "开发环境",
           [U + "\\anaconda3\\pkgs", U + "\\miniconda3\\pkgs",
            LA + "\\anaconda3\\pkgs", LA + "\\miniconda3\\pkgs"], "",
           "conda 解压后的包目录，常占十几 GB。", "caution"),
    Target("hf_cache", "HuggingFace 模型缓存", "开发环境",
           [U + "\\.cache\\huggingface"], U + "\\.cache\\huggingface",
           "下载的模型权重，单个模型可达数十 GB。", "safe",
           env=(("HF_HOME", "{dst}"),)),
    Target("torch_cache", "PyTorch 模型缓存", "开发环境",
           [U + "\\.cache\\torch"], U + "\\.cache\\torch",
           "torch.hub 下载的预训练权重。", "safe", env=(("TORCH_HOME", "{dst}"),)),
    Target("android_sdk", "Android SDK", "开发环境",
           [LA + "\\Android\\Sdk"], LA + "\\Android\\Sdk",
           "SDK、构建工具与系统镜像。", "caution",
           env=(("ANDROID_SDK_ROOT", "{dst}"), ("ANDROID_HOME", "{dst}"))),
    Target("android_avd", "Android 模拟器镜像", "开发环境",
           [U + "\\.android\\avd"], U + "\\.android\\avd",
           "AVD 虚拟设备镜像，每个 8-30 GB。", "caution",
           env=(("ANDROID_AVD_HOME", "{dst}"),)),
    Target("vscode_ext", "VS Code 扩展", "开发环境",
           [U + "\\.vscode\\extensions"], U + "\\.vscode\\extensions",
           "已安装扩展目录。", "safe", procs=("Code.exe",)),
    Target("jetbrains", "JetBrains 索引缓存", "开发环境",
           [LA + "\\JetBrains"], LA + "\\JetBrains",
           "IDEA / PyCharm 等的索引与日志缓存，删了会自动重建。", "caution",
           procs=("idea64.exe", "pycharm64.exe")),
    Target("unity_cache", "Unity 缓存", "开发环境",
           [LA + "\\Unity\\cache"], LA + "\\Unity\\cache",
           "Unity 资源导入缓存。", "safe", procs=("Unity.exe",)),

    # ---------------------------------------------------------------- 用户目录
    Target("downloads", "下载文件夹", "用户目录",
           [U + "\\Downloads"], U + "\\Downloads",
           "浏览器与软件的默认下载位置，通常最占空间。", "safe"),
    Target("video_captures", "游戏录像 (Captures)", "用户目录",
           [U + "\\Videos\\Captures"], U + "\\Videos\\Captures",
           "Xbox Game Bar 录制的视频。", "safe"),

    # ---------------------------------------------------------------- 手动项
    Target("docker_wsl", "Docker / WSL 虚拟磁盘", "手动处理", [], "",
           "ext4.vhdx 动辄几十 GB，必须用官方命令迁移，不能用链接。",
           "manual", kind="manual",
           manual="1) 关闭 Docker Desktop 与 WSL：wsl --shutdown\n"
                  "2) 导出：wsl --export docker-desktop-data D:\\wsl\\ddd.tar\n"
                  "3) 注销：wsl --unregister docker-desktop-data\n"
                  "4) 导入：wsl --import docker-desktop-data D:\\wsl\\docker-data D:\\wsl\\ddd.tar --version 2\n"
                  "5) 重启 Docker Desktop 验证。"),
    Target("steam_lib", "Steam 游戏库", "手动处理", [], "",
           "Steam 自带库迁移，直接搬会丢注册信息。", "manual", kind="manual",
           manual="Steam → 设置 → 存储空间 → 添加 D 盘库文件夹 → 勾选游戏 → 移动。"),
    Target("pagefile", "虚拟内存页面文件", "手动处理", [], "",
           "pagefile.sys 常驻 C 盘根部，几 GB 到几十 GB。", "manual",
           kind="manual", admin=True,
           manual="Win+R 输入 sysdm.cpl → 高级 → 性能设置 → 高级 → 更改虚拟内存\n"
                  "取消“自动管理”，C 盘设为“无分页文件”，D 盘设为“系统管理的大小” → 重启。"),
    Target("hiberfil", "休眠文件 hiberfil.sys", "手动处理", [], "",
           "休眠文件大小≈内存的 40%-100%。", "manual", kind="manual", admin=True,
           manual="管理员 CMD 执行：powercfg /h off\n（会同时关闭快速启动；如需保留快速启动可执行 powercfg /h /type reduced）"),
]


def by_id(tid: str):
    for t in TARGETS:
        if t.id == tid:
            return t
    return None


def default_dest_root() -> str:
    """选一个非 C 盘、剩余空间最大的盘作为迁移落点。"""
    import string
    best, best_free = "", -1
    for letter in string.ascii_uppercase[2:]:
        root = f"{letter}:\\"
        if not os.path.exists(root):
            continue
        try:
            import shutil
            u = shutil.disk_usage(root)
        except Exception:
            continue
        if u.free > best_free:
            best, best_free = root, u.free
    return os.path.join(best or "D:\\", "CDiskSaver")
