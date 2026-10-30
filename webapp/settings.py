# -*- coding: utf-8 -*-
"""设置项读写：默认输出目录、引擎路径、上传大小上限，JSON 文件持久化。

设置文件保存在程序基目录下，字段与界面设置对话框一一对应；
读取时逐字段回退到默认值，文件缺失或损坏不视为错误。
"""

import json
import sys
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
}


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
    return data


def save(data, base_dir=None):
    """把设置写入 JSON 文件（UTF-8，无 BOM）。"""
    payload = {key: data.get(key, DEFAULTS[key]) for key in DEFAULTS}
    payload["upload_limit_mb"] = clamp_upload_limit(payload["upload_limit_mb"])
    settings_path(base_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload
