# -*- coding: utf-8 -*-
"""文件夹格式巡检（F8）：按用户的多条规则持续监听文件夹，报告并按需自动转换违规文件。

规则来自 settings 的 watch_rules 列表（每条：folder / format / auto_convert），
由服务层共享的 settings 字典实时读取，改规则无需重启线程。巡检只扫描文件夹
第一层；跳过隐藏/临时文件与最近写入的文件（防半成品误报）。

自动转换：规则开启 auto_convert 时，新出现的「格式不符」违规文件经注入的
回调（服务层复制进上传链路）按该规则期望格式创建转换任务；同一文件内容
未变化（mtime+size 指纹相同）不会重复转换。
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


def normalize_rules(raw_rules):
    """规范化规则列表：丢弃无效/重复文件夹条目，补 id 与布尔标记。"""
    rules = []
    seen = set()
    for item in raw_rules or []:
        if not isinstance(item, dict):
            continue
        folder = str(item.get("folder") or "").strip()
        fmt = str(item.get("format") or "").strip().lower()
        if not folder or fmt not in ec.OUTPUT_FORMATS:
            continue
        key = folder.lower()
        if key in seen:
            continue
        seen.add(key)
        rules.append({
            "id": str(item.get("id") or len(rules) + 1),
            "folder": folder,
            "format": fmt,
            "auto_convert": bool(item.get("auto_convert")),
        })
    return rules


class FolderWatcher:
    """多规则巡检器：后台线程轮询，状态经 snapshot() 供接口查询。"""

    def __init__(self, settings_data, auto_convert_handler=None):
        self._settings = settings_data  # 与 api/settings 共享的可变字典
        self._auto_convert = auto_convert_handler  # (paths, fmt) -> 创建任务数
        self._lock = threading.Lock()
        self._notified = set()   # 已提示过的违规路径（文件移走后再出现会重新提示）
        self._auto_done = {}     # 已自动转换的 path -> (mtime, size) 指纹
        self._stop = threading.Event()
        self._thread = None
        self._state = {
            "reachable": None,   # 兼容保留：全部规则可达时 True
            "unreachable": [],   # 不可达的规则文件夹
            "last_scan": None,
            "violations": [],    # [{name, path, kind, rule_format, rule_id}]
            "fresh": [],         # 本轮新出现的违规路径（用于一次性提示）
            "auto_converted": [],  # 本轮自动转换的文件名
        }

    # ── 巡检 ──

    def scan_once(self):
        """执行一轮多规则巡检并更新状态，返回 state。"""
        rules = normalize_rules(self._settings.get("watch_rules"))
        violations = []
        unreachable = []
        now = time.time()
        for rule in rules:
            folder = Path(rule["folder"])
            if not folder.is_dir():
                unreachable.append(rule["folder"])
                continue
            for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
                if not entry.is_file() or entry.name.startswith((".", "~$", "$")):
                    continue
                try:
                    if now - entry.stat().st_mtime < STABLE_WINDOW_SECONDS:
                        continue  # 刚出现的文件，等它写完再判
                except OSError:
                    continue
                kind = classify(entry, rule["format"])
                if kind is not None:
                    violations.append({
                        "name": entry.name,
                        "path": str(entry),
                        "kind": kind,
                        "rule_format": rule["format"],
                        "rule_id": rule["id"],
                        "auto_convert": rule["auto_convert"],
                    })

        with self._lock:
            paths = {v["path"] for v in violations}
            fresh = [p for p in paths if p not in self._notified]
            self._notified &= paths          # 移走的违规解除"已提示"标记
            self._notified |= paths
            self._state.update(
                reachable=not unreachable if rules else None,
                unreachable=unreachable,
                last_scan=time.time(),
                violations=violations,
                fresh=fresh,
                auto_converted=[],
            )
            if fresh:
                log.info("监听发现 %d 个新违规文件", len(fresh))
            self._auto_convert_violations(violations, fresh)
            return self._snapshot_locked()

    def _auto_convert_violations(self, violations, fresh):
        """对新出现的「格式不符」违规执行规则级自动转换（锁内调用）。"""
        if self._auto_convert is None:
            return
        fresh_set = set(fresh)
        for v in violations:
            if v["kind"] != KIND_WRONG_FORMAT or v["path"] not in fresh_set:
                continue
            if not v["auto_convert"]:
                continue
            try:
                stat = Path(v["path"]).stat()
            except OSError:
                continue
            fingerprint = (stat.st_mtime, stat.st_size)
            if self._auto_done.get(v["path"]) == fingerprint:
                continue  # 内容没变，不重复自动转换
            created = self._auto_convert([v["path"]], v["rule_format"])
            if created:
                self._auto_done[v["path"]] = fingerprint
                self._state["auto_converted"].append(v["name"])
                log.info("监听自动转换：%s -> %s", v["name"], v["rule_format"])

    def _snapshot_locked(self):
        snap = {k: (list(v) if isinstance(v, list) else v) for k, v in self._state.items()}
        snap["violations"] = [dict(v) for v in self._state["violations"]]
        return snap

    def snapshot(self):
        """当前监听配置与状态（供 GET /api/watch）。"""
        with self._lock:
            snap = self._snapshot_locked()
        rules = normalize_rules(self._settings.get("watch_rules"))
        snap["rules"] = rules
        snap["enabled"] = bool(rules)
        try:
            snap["interval"] = max(MIN_INTERVAL, min(MAX_INTERVAL,
                                                     int(self._settings.get("watch_interval") or DEFAULT_INTERVAL)))
        except (TypeError, ValueError):
            snap["interval"] = DEFAULT_INTERVAL
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
        while not self._stop.wait(self.snapshot().get("interval", DEFAULT_INTERVAL)):
            try:
                self.scan_once()
            except Exception as exc:  # 巡检线程绝不退出
                log.warning("监听巡检异常: %s", exc)
