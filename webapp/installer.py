# -*- coding: utf-8 -*-
"""引擎安装器：下载官方便携版 Calibre 解压到程序目录，或调用 winget 安装标准版。

也支持本地上传已下载好的便携版安装包（mode=local），全程不触网。
安装在新后台线程执行，全局状态经 install_state() 轮询（引导对话框每秒查询）。
下载失败属预期风险（官方下载服务器部分网络环境不可达），失败后引导页的
本地安装包、winget 与官网手动下载入口仍可用。
"""

import logging
import subprocess
import threading
import urllib.request
from pathlib import Path

import shutil

log = logging.getLogger("ebook-converter")

# 官方稳定入口（302 重定向到下载服务器）；实施实测该入口有效，
# 但下载服务器在部分网络环境直连超时——失败时引导用户改用本地安装包、winget 或官网手动下载
PORTABLE_URL = "https://calibre-ebook.com/dist/portable"
WINGET_CMD = ["winget", "install", "--id", "calibre.calibre", "-e",
              "--accept-source-agreements", "--accept-package-agreements"]

# 本地安装包下限：官方便携版安装器约 100+ MB，1MB 以下基本可判为损坏/选错文件
MIN_LOCAL_PACKAGE_BYTES = 1 * 1024 * 1024

_state = {"active": False, "state": "idle", "progress": 0, "message": ""}
_lock = threading.Lock()


def install_state():
    with _lock:
        return dict(_state)


def _set_state(**kw):
    with _lock:
        _state.update(kw)


def reset_state():
    _set_state(active=False, state="idle", progress=0, message="")


def _download(url, dest, progress_cb=None):
    """流式下载到 dest，progress_cb 收到 0-100 的整数百分比。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ebook-converter/1.1"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress_cb and total:
                progress_cb(min(100, done * 100 // total))


class EngineInstaller:
    """按模式安装引擎；同一时刻只允许一个安装任务。"""

    def __init__(self, base):
        self.base = Path(base)

    def start(self, mode, package_path=None):
        if mode not in ("portable", "winget", "local"):
            raise ValueError(f"未知安装方式: {mode}")
        if mode == "local" and not package_path:
            raise ValueError("local 模式需要 package_path")
        with _lock:
            if _state["active"]:
                return False
            msg = {
                "portable": "准备下载",
                "winget": "正在启动 winget",
                "local": "正在准备本地安装包",
            }[mode]
            _state.update(active=True,
                          state="downloading" if mode == "portable" else "installing",
                          progress=0, message=msg)
        threading.Thread(target=self._run, args=(mode, package_path), daemon=True,
                         name="engine-installer").start()
        return True

    def wait_done(self, timeout=600):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline and _state["active"]:
            time.sleep(0.05)
        return not _state["active"]

    def _extract_portable(self, installer_exe, target):
        """运行便携版安装器把引擎解压到 target（与下载版共用同一命令）。"""
        target.mkdir(parents=True, exist_ok=True)
        return subprocess.run([str(installer_exe), str(target)], capture_output=True,
                              text=True, timeout=3600, encoding="utf-8", errors="replace")

    def _run(self, mode, package_path=None):
        try:
            if mode == "winget":
                _set_state(state="installing", message="正在通过 winget 安装 Calibre（官方源）")
                proc = subprocess.run(WINGET_CMD, capture_output=True, text=True,
                                      timeout=3600, encoding="utf-8", errors="replace")
                if proc.returncode != 0:
                    tail = (proc.stderr or proc.stdout or "").strip()[-200:]
                    _set_state(state="failed", message=tail or "winget 安装失败")
                    log.warning("winget 安装失败: %s", tail)
                    return
            elif mode == "local":
                dest = Path(package_path)
                if dest.suffix.lower() != ".exe" or not dest.is_file():
                    _set_state(state="failed", message="安装包无效或损坏")
                    log.warning("本地安装包无效：%s", dest)
                    return
                if dest.stat().st_size < MIN_LOCAL_PACKAGE_BYTES:
                    _set_state(state="failed", message="安装包无效或损坏（文件过小）")
                    log.warning("本地安装包过小：%s", dest)
                    return
                _set_state(state="extracting", progress=0, message="正在解压本地安装包到程序目录")
                log.info("开始解压本地安装包：%s", dest)
                target = self.base / "engines" / "calibre"
                proc = self._extract_portable(dest, target)
                if proc.returncode != 0:
                    tail = (proc.stderr or proc.stdout or "").strip()[-200:]
                    _set_state(state="failed", message=tail or "安装包无效或损坏")
                    log.warning("本地安装包解压失败: %s", tail)
                    return
                # 上传副本落在程序 tmp 目录内才清理，用户磁盘上的原文件不动
                try:
                    dest.resolve().relative_to((self.base / "tmp").resolve())
                    dest.unlink(missing_ok=True)
                except (ValueError, OSError):
                    pass
            else:
                # portable（与现网一致：下载后再解压）
                dest = self.base / "tmp" / "calibre-portable-installer.exe"
                dest.parent.mkdir(parents=True, exist_ok=True)
                _set_state(state="downloading", message="正在下载便携版引擎（约 100+ MB）")
                _download(PORTABLE_URL, dest, lambda pct: _set_state(progress=pct))
                log.info("便携版安装器下载完成：%s", dest)
                _set_state(state="extracting", progress=100, message="正在解压到程序目录")
                target = self.base / "engines" / "calibre"
                proc = self._extract_portable(dest, target)
                if proc.returncode != 0:
                    tail = (proc.stderr or proc.stdout or "").strip()[-200:]
                    _set_state(state="failed", message=tail or "便携版解压失败")
                    log.warning("便携版解压失败: %s", tail)
                    return
                dest.unlink(missing_ok=True)
            _set_state(state="done", progress=100, message="安装完成，正在重新检测")
            log.info("引擎安装完成（%s）", mode)
        except Exception as exc:
            _set_state(state="failed",
                       message=f"安装失败：{exc}。可改用本地安装包、winget 或到官网手动下载。")
            log.warning("引擎安装失败: %s", exc)
            return
        finally:
            _set_state(active=False)
