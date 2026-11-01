# -*- coding: utf-8 -*-
"""设置项读写：默认输出目录、引擎路径、上传大小上限、文件夹监听规则。

监听规则自 V1.3 起为列表结构（watch_rules）；V1.2 的单规则字段
（watch_enabled/watch_folder/watch_format）读取时一次性迁移，不再使用。
"""

import json
import sys
import uuid
from pathlib import Path

DEFAULT_UPLOAD_LIMIT_MB = 200
MIN_UPLOAD_LIMIT_MB = 1
MAX_UPLOAD_LIMIT_MB = 4096

# output_dir / engine_path 为空字符串表示"未设置"：
# 输出目录回退到基目录下 converted，引擎路径回退到自动探测
DEFAULTS = {
    "output_dir": "",
    "engine_path": "",
    "upload_limit_mb": DEFAULT_UPLOAD_LIMIT_MB,
    # 文件夹监听（F8）：每条规则要求某文件夹内文件全部为某格式
    "watch_rules": [],
    "watch_interval": 5,
}

# 旧单规则字段：仅用于从 V1.2 settings.json 迁移，读出后不再写回
LEGACY_WATCH_FIELDS = ("watch_enabled", "watch_folder", "watch_format")


def base_dir():
    """程序基目录：PyInstaller 打包后取 exe 所在目录，脚本运行取当前工作目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def settings_path(base_dir=None):
    return Path(base_dir) / "settings.json" if base_dir else base_dir() / "settings.json"


def clamp_upload_limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_UPLOAD_LIMIT_MB
    return max(MIN_UPLOAD_LIMIT_MB, min(MAX_UPLOAD_LIMIT_MB, limit))


def migrate_watch(data):
    """V1.2 单规则字段一次性迁移为 watch_rules 列表（缺省补空列表）。"""
    if not data.get("watch_rules"):
        rules = []
        if str(data.get("watch_folder") or "").strip():
            rules.append({
                "id": uuid.uuid4().hex[:12],
                "folder": str(data["watch_folder"]).strip(),
                "format": str(data.get("watch_format") or "epub").strip().lower(),
                "auto_convert": False,
            })
        data["watch_rules"] = rules
    return data


def load(base_dir=None):
    """读取设置，逐字段回退默认值；文件不存在或损坏时返回默认设置。"""
    data = dict(DEFAULTS)
    path = settings_path(base_dir)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        for key in DEFAULTS:
            if isinstance(raw, dict) and raw.get(key) is not None:
                data[key] = raw[key]
    data["upload_limit_mb"] = clamp_upload_limit(data["upload_limit_mb"])
    migrate_watch(data)
    return data


def save(data, base_dir=None):
    """把设置写入 JSON 文件（UTF-8，无 BOM）。"""
    payload = {key: data.get(key, DEFAULTS[key]) for key in DEFAULTS}
    payload["upload_limit_mb"] = clamp_upload_limit(payload["upload_limit_mb"])
    if not isinstance(payload["watch_rules"], list):
        payload["watch_rules"] = []
    settings_path(base_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload
