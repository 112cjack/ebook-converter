# -*- coding: utf-8 -*-
"""REST 路由：全部返回 JSON。

页面唯一的数据同步手段是轮询 GET /api/tasks；除技术方案表 5 的七组接口外，
另提供 POST /api/remove 支持界面原型的「移除文件 / 清空列表」交互（方案未覆盖
的就近扩展，已在技术方案文档补记）。
"""

import logging
import os
import shutil
import string
import subprocess
import sys
import time
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

import ebook_converter as ec
from . import installer
from . import settings as settings_mod
from . import tasks as tasks_mod

bp = Blueprint("api", __name__)

log = logging.getLogger("ebook-converter")


def _manager():
    return current_app.extensions["task_manager"]


def _settings_data():
    return current_app.extensions["settings_data"]


def engine_state():
    """引擎检测结论：未检测到时 installed=False，页面据此显示安装引导。"""
    manager = _manager()
    engine = manager.resolve_engine()
    manual = str(_settings_data().get("engine_path") or "").strip()
    state = {
        "installed": engine is not None,
        "path": str(engine) if engine else None,
        "source": None,
        "version": None,
        "install": installer.install_state(),
    }
    if engine is not None:
        state["source"] = "manual" if manual and _same_file(manual, engine) else "auto"
        state["version"] = _engine_version(engine)
    return state


def _same_file(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return str(a) == str(b)


def _engine_version(engine):
    """ebook-convert --version 的首行输出，按路径缓存避免重复起子进程。"""
    cache = current_app.extensions["engine_versions"]
    key = str(engine)
    if key not in cache:
        try:
            proc = subprocess.run(
                [str(engine), "--version"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=15,
            )
            first_line = (proc.stdout or proc.stderr or "").strip().splitlines()
            cache[key] = first_line[0] if first_line else None
        except (OSError, subprocess.TimeoutExpired):
            cache[key] = None
    return cache[key]


def public_upload(record):
    return {
        "id": record["id"],
        "name": record["name"],
        "size": record["size"],
        "format": record["format"],
        "removed": record["removed"],
        "truncated": record.get("truncated", False),
        "scanned_pdf": record.get("scanned_pdf", False),
    }


def public_task(task):
    return {
        "id": task["id"],
        "upload_id": task["upload_id"],
        "name": task["name"],
        "format_in": task["format_in"],
        "format_out": task["format_out"],
        "status": task["status"],
        "status_label": tasks_mod.STATUS_LABEL[task["status"]],
        "progress": task["progress"],
        "message": task["message"],
        "error": task["error"],
        "error_detail": task["error_detail"],
        "output_path": task["output_path"],
        "output_dir": task["output_dir"],
        "created_at": task["created_at"],
        "finished_at": task["finished_at"],
    }


def public_settings(data):
    return {
        "output_dir": data.get("output_dir", ""),
        "engine_path": data.get("engine_path", ""),
        "upload_limit_mb": data.get("upload_limit_mb", settings_mod.DEFAULT_UPLOAD_LIMIT_MB),
    }


@bp.get("/api/status")
def get_status():
    """页面加载时调用：引擎检测状态、格式表与设置摘要。"""
    data = _settings_data()
    return jsonify({
        "app": "电子书转换器",
        "engine": engine_state(),
        "output_formats": list(ec.OUTPUT_FORMATS),
        "input_extensions": sorted(ec.INPUT_EXTENSIONS),
        "settings": public_settings(data),
        "frozen": bool(getattr(sys, "frozen", False)),
    })


@bp.post("/api/upload")
def upload():
    """上传一个或多个文件到工作目录，按扩展名白名单过滤并返回任务预告。"""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "未收到文件，请选择要转换的文件"}), 400
    accepted, rejected = [], []
    for item in files:
        name = item.filename or ""
        ext = Path(name).suffix.lower()
        if ext not in ec.INPUT_EXTENSIONS:
            rejected.append({"name": name, "reason": "不支持的文件格式"})
            continue
        data = item.read()
        if not data:
            rejected.append({"name": name, "reason": "文件内容为空"})
            continue
        record = _manager().store_upload(name, data)
        accepted.append(public_upload(record))
    return jsonify({"uploads": accepted, "rejected": rejected}), 201


@bp.post("/api/convert")
def convert():
    """以 JSON 提交目标格式与输出目录，为已上传文件创建批量任务。"""
    body = request.get_json(silent=True) or {}
    fmt = str(body.get("format") or "").strip().lower()
    if fmt not in ec.OUTPUT_FORMATS:
        choices = " / ".join(ec.OUTPUT_FORMATS)
        return jsonify({"error": f"不支持的输出格式，请从 {choices} 中选择"}), 400

    manager = _manager()
    ids = body.get("upload_ids") or [
        record["id"] for record in manager.uploads.values() if not record["removed"]
    ]
    if not ids:
        return jsonify({"error": "没有可转换的文件，请先上传"}), 400

    data = _settings_data()
    raw_dir = str(body.get("output_dir") or data.get("output_dir") or "").strip()
    if not raw_dir:
        raw_dir = str(Path(current_app.extensions["base_dir"]) / "converted")
    out_dir = Path(raw_dir)
    if not out_dir.is_absolute():
        return jsonify({"error": "输出目录必须是绝对路径"}), 400
    if _same_file(out_dir, manager.upload_dir):
        return jsonify({"error": "输出目录不能使用程序的上传目录"}), 400
    # 目录通过校验即登记，open-folder 之后才能放行
    manager.registered_dirs.add(str(out_dir.resolve()))

    try:
        created = manager.create_tasks(ids, fmt, out_dir,
                                       overwrite=bool(body.get("overwrite")))
    except ec.EngineNotFoundError as exc:
        return jsonify({"error": str(exc), "engine": engine_state()}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not created:
        return jsonify({"error": "所选文件不存在或已移除"}), 400
    return jsonify({"tasks": [public_task(t) for t in created]}), 201


@bp.get("/api/tasks")
def list_tasks():
    """返回全部任务（含历史）当前状态，前端轮询此接口。"""
    uploads, tasks = _manager().snapshot()
    return jsonify({
        "uploads": [public_upload(u) for u in uploads],
        "tasks": [public_task(t) for t in tasks],
        "now": time.time(),
    })


@bp.post("/api/cancel")
def cancel_task():
    """取消一个转换中的任务（worker 在引擎子进程的轮询点终止它）。"""
    body = request.get_json(silent=True) or {}
    task_id = str(body.get("task_id") or "")
    if not task_id or not _manager().request_cancel(task_id):
        return jsonify({"error": "任务不存在或不在转换中"}), 400
    return jsonify({"ok": True})


@bp.post("/api/install-engine")
def install_engine():
    """后台安装转换引擎：便携版下载解压到程序目录（默认）或 winget 安装标准版。"""
    body = request.get_json(silent=True) or {}
    mode = str(body.get("mode") or "portable")
    if mode not in ("portable", "winget"):
        return jsonify({"error": "未知的安装方式"}), 400
    if mode == "winget" and shutil.which("winget") is None:
        return jsonify({"error": "本机没有 winget，请下载便携版引擎或到官网手动安装"}), 400
    started = installer.EngineInstaller(current_app.extensions["base_dir"]).start(mode)
    if not started:
        return jsonify({"error": "已有安装任务在进行中"}), 409
    log.info("开始安装引擎（%s）", mode)
    return jsonify({"ok": True, "install": installer.install_state()}), 202


@bp.post("/api/create-shortcut")
def create_shortcut():
    """在用户桌面创建指向本程序的快捷方式（仅打包版有意义）。"""
    if not getattr(sys, "frozen", False):
        return jsonify({"error": "仅打包版支持创建桌面快捷方式，脚本版请使用 start.bat"}), 400
    target = Path(sys.executable)
    quote = chr(39)
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$lnk = [IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), "
        f"'电子书转换器.lnk'); "
        "$s = $ws.CreateShortcut($lnk); "
        f"$s.TargetPath = '{str(target).replace(quote, quote * 2)}'; "
        f"$s.WorkingDirectory = '{str(target.parent).replace(quote, quote * 2)}'; "
        "$s.Save()"
    )
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                              capture_output=True, text=True, timeout=30,
                              encoding="utf-8", errors="replace")
    except OSError as exc:
        return jsonify({"error": f"创建快捷方式失败: {exc}"}), 500
    if proc.returncode != 0:
        return jsonify({"error": "创建快捷方式失败: " + (proc.stderr or "").strip()[-200:]}), 500
    log.info("已创建桌面快捷方式 -> %s", target)
    return jsonify({"ok": True})


def list_drives():
    """本机可用盘符（Windows，如 "C:"）；其他平台返回根目录。"""
    if sys.platform == "win32":
        return [f"{c}:" for c in string.ascii_uppercase if Path(f"{c}:/").exists()]
    return ["/"]


@bp.get("/api/browse")
def browse():
    """输出目录浏览器数据源：path 为空返回盘符列表，否则返回该目录下的子目录。"""
    raw = str(request.args.get("path") or "").strip()
    if not raw:
        suffix = "\\" if sys.platform == "win32" else ""
        return jsonify({
            "current": None,
            "parent": None,
            "entries": [{"name": drive, "path": drive + suffix} for drive in list_drives()],
        })
    path = Path(raw)
    if not path.is_absolute():
        return jsonify({"error": "路径必须是绝对路径"}), 400
    if not path.is_dir():
        return jsonify({"error": "目录不存在"}), 400
    entries = []
    try:
        for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
            if child.name.startswith((".", "$")):
                continue
            if child.is_dir():
                entries.append({"name": child.name, "path": str(child)})
    except OSError as exc:
        return jsonify({"error": f"无法读取目录: {exc}"}), 400
    parent = str(path.parent) if path.parent != path else None
    return jsonify({"current": str(path), "parent": parent, "entries": entries})


@bp.post("/api/remove")
def remove():
    """把上传从列表移除并删除临时文件；任务记录保留为历史。缺省清空全部可移除项。"""
    body = request.get_json(silent=True) or {}
    manager = _manager()
    requested = body.get("upload_ids")
    if requested is None:
        requested = manager.removable_upload_ids()
    removable = set(manager.removable_upload_ids())
    to_remove = [uid for uid in requested if uid in removable]
    busy = [uid for uid in requested if uid not in removable]
    manager.remove_uploads(to_remove)
    return jsonify({"removed": to_remove, "busy": busy})


@bp.post("/api/open-folder")
def open_folder():
    """调用系统文件管理器打开输出目录（仅限服务层已登记的目录）。"""
    body = request.get_json(silent=True) or {}
    raw = str(body.get("path") or "").strip()
    if not raw:
        return jsonify({"error": "缺少 path 参数"}), 400
    try:
        path = Path(raw).resolve()
    except OSError:
        return jsonify({"error": "路径无效"}), 400
    manager = _manager()
    registered = {str(Path(item).resolve()) for item in manager.registered_dirs}
    if str(path) not in registered:
        return jsonify({"error": "只能打开程序登记过的输出目录"}), 403
    if not path.is_dir():
        return jsonify({"error": "目录不存在，请先完成一次转换"}), 404
    open_in_explorer(path)
    return jsonify({"ok": True})


def open_in_explorer(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - 本机工具打开用户已登记目录
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


@bp.get("/api/settings")
def get_settings():
    data = _settings_data()
    return jsonify({**public_settings(data), "engine": engine_state()})


@bp.post("/api/settings")
def post_settings():
    """读取或保存设置：默认输出目录、引擎路径、上传大小上限。"""
    body = request.get_json(silent=True) or {}
    data = _settings_data()

    if "output_dir" in body:
        value = str(body["output_dir"] or "").strip()
        if value and not Path(value).is_absolute():
            return jsonify({"error": "输出目录必须是绝对路径"}), 400
        data["output_dir"] = value

    if "engine_path" in body:
        value = str(body["engine_path"] or "").strip()
        if value and not Path(value).is_file():
            return jsonify({"error": "指定的引擎文件不存在，请确认路径"}), 400
        data["engine_path"] = value

    if "upload_limit_mb" in body:
        try:
            limit = int(body["upload_limit_mb"])
        except (TypeError, ValueError):
            return jsonify({"error": "上传上限必须是整数（MB）"}), 400
        if not (settings_mod.MIN_UPLOAD_LIMIT_MB <= limit <= settings_mod.MAX_UPLOAD_LIMIT_MB):
            return jsonify({"error": "上传上限需在 1~4096 MB 之间"}), 400
        data["upload_limit_mb"] = limit

    if data["output_dir"]:
        try:
            Path(data["output_dir"]).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return jsonify({"error": f"输出目录不可用: {exc}"}), 400

    settings_mod.save(data, base_dir=current_app.extensions["base_dir"])
    current_app.config["MAX_CONTENT_LENGTH"] = data["upload_limit_mb"] * 1024 * 1024

    manager = _manager()
    if data["output_dir"]:
        manager.registered_dirs.add(str(Path(data["output_dir"]).resolve()))
    log.info("设置已保存：输出目录=%r 引擎路径=%r 上传上限=%dMB",
             data["output_dir"], data["engine_path"], data["upload_limit_mb"])
    return jsonify({**public_settings(data), "engine": engine_state()})
