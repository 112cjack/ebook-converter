# -*- coding: utf-8 -*-
"""文件夹格式巡检（F8）：按用户规则持续监听一个文件夹，报告违规文件。

规则来自 settings（watch_enabled / watch_folder / watch_format / watch_interval），
由服务层共享的 settings 字典实时读取，修改规则无需重启线程。
巡检只扫描文件夹第一层；跳过隐藏/临时文件与最近写入的文件（防半成品误报）。
"""

import logging
import threading
import time
from pathlib import Path

import ebook_converter as ec

log = logging.getLogger("ebook-converter")

# 跳过最近 N 秒内修改的文件：正在复制/下载的半成品会误报
STABLE_WINDOW_SECONDS = 10

KIND_UNCONVERTIBLE = "unconvertible"  # 程序无法识别/转换
KIND_WRONG_FORMAT = "wrong_format"    # 可转换但与期望格式不符
KIND_LABEL = {
    KIND_UNCONVERTIBLE: "无法转换",
    KIND_WRONG_FORMAT: "格式不符",
}

DEFAULT_INTERVAL = 5
MIN_INTERVAL = 5
MAX_INTERVAL = 60


def classify(entry, expected_format):
    """返回违规类别；符合期望格式返回 None。"""
    ext = entry.suffix.lower().lstrip(".")
    if ext == expected_format:
        return None
    if ext in ec.OUTPUT_FORMATS or ("." + ext) in ec.INPUT_EXTENSIONS:
        return KIND_WRONG_FORMAT
    return KIND_UNCONVERTIBLE


class FolderWatcher:
    """单文件夹巡检器：后台线程轮询，状态经 snapshot() 供接口查询。"""

    def __init__(self, settings_data):
        self._settings = settings_data  # 与 api/settings 共享的可变字典
        self._lock = threading.Lock()
        self._notified = set()   # 已提示过的违规路径（文件移走后再出现会重新提示）
        self._stop = threading.Event()
        self._thread = None
        self._state = {
            "reachable": None,
            "last_scan": None,
            "violations": [],   # [{name, path, kind}]
            "fresh": [],        # 本轮新出现的违规路径（用于一次性提示）
        }

    # ── 配置读取 ──

    def _config(self):
        return {
            "enabled": bool(self._settings.get("watch_enabled")),
            "folder": str(self._settings.get("watch_folder") or "").strip(),
            "format": str(self._settings.get("watch_format") or "epub").strip().lower(),
            "interval": max(MIN_INTERVAL, min(MAX_INTERVAL, int(self._settings.get("watch_interval") or DEFAULT_INTERVAL))),
        }

    # ── 巡检 ──

    def scan_once(self):
        """执行一轮巡检并更新状态，返回 (config, state)。"""
        config = self._config()
        violations = []
        reachable = None
        if config["enabled"] and config["folder"]:
            folder = Path(config["folder"])
            reachable = folder.is_dir()
            if reachable:
                now = time.time()
                for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
                    if not entry.is_file() or entry.name.startswith((".", "~$", "$")):
                        continue
                    try:
                        if now - entry.stat().st_mtime < STABLE_WINDOW_SECONDS:
                            continue  # 刚出现的文件，等它写完再判
                    except OSError:
                        continue
                    kind = classify(entry, config["format"])
                    if kind is not None:
                        violations.append({"name": entry.name, "path": str(entry), "kind": kind})

        with self._lock:
            if config["enabled"]:
                paths = {v["path"] for v in violations}
                fresh = [p for p in paths if p not in self._notified]
                self._notified &= paths          # 移走的违规解除"已提示"标记
                self._notified |= paths
                self._state.update(reachable=reachable, last_scan=time.time(),
                                   violations=violations, fresh=fresh)
                if fresh:
                    log.info("监听发现 %d 个新违规文件（%s）", len(fresh), config["folder"])
            else:
                self._notified.clear()
                self._state.update(reachable=None, last_scan=time.time(),
                                   violations=[], fresh=[])
            return dict(config), self._snapshot_locked()

    def _snapshot_locked(self):
        snap = dict(self._state)
        snap["violations"] = [dict(v) for v in self._state["violations"]]
        return snap

    def snapshot(self):
        """当前监听配置与状态（供 GET /api/watch）。"""
        with self._lock:
            snap = self._snapshot_locked()
        snap.update(self._config())
        snap["last_scan"] = self._state["last_scan"]
        return snap

    # ── 线程管理 ──

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="folder-watcher")
        self._thread.start()
        log.info("文件夹监听线程已启动")

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self._config()["interval"]):
            try:
                self.scan_once()
            except Exception as exc:  # 巡检线程绝不退出
                log.warning("监听巡检异常: %s", exc)
