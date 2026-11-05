# -*- coding: utf-8 -*-
"""Web 服务层：Flask 应用工厂、REST 路由、任务队列与设置读写。

目录结构遵循《电子书转换器技术方案》第 6 章；
启动方式见 app.py（python -m webapp.app）。
"""

import atexit
import logging
import shutil
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import ebook_converter as ec

from . import api, settings
from .tasks import TaskManager
from .watcher import FolderWatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ebook-converter")


def find_portable_engine(base):
    """兼容旧导入；实现已下沉到 ebook_converter。"""
    return ec.find_portable_engine(base)


def make_engine_resolver(settings_data, base):
    """引擎解析：委托 ebook_converter.resolve_engine（顺序与 CLI 一致）。"""
    def resolve():
        return ec.resolve_engine(
            base_dir=base,
            manual_path=settings_data.get("engine_path"),
        )
    return resolve


def make_auto_convert_handler(manager, settings_data, base):
    """监听自动转换回调：把违规文件复制进上传链路并按规则期望格式创建任务。

    引擎未就绪或文件不可读时返回 0（watcher 记不住指纹，下轮可再试）。
    """
    def convert(paths, fmt):
        if manager.resolve_engine() is None:
            return 0
        ids = []
        for path in paths:
            try:
                content = Path(path).read_bytes()
            except OSError:
                continue
            record = manager.store_upload(Path(path).name, content)
            ids.append(record["id"])
        if not ids:
            return 0
        out_dir = str(settings_data.get("output_dir") or "").strip() or str(Path(base) / "converted")
        created = manager.create_tasks(ids, fmt, Path(out_dir))
        return len(created)
    return convert


def create_app(base_dir=None, testing=False):
    """构建 Flask 应用：装配设置、任务管理器、路由与错误处理。"""
    base = Path(base_dir) if base_dir else settings.base_dir()
    upload_dir = base / "tmp" / "uploads"
    # 启动时清空上次运行的残留上传（内存任务此刻必然为空，残留全是垃圾）
    shutil.rmtree(upload_dir, ignore_errors=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, static_folder="static", static_url_path="")
    app.config["TESTING"] = testing

    settings_data = settings.load(base)
    app.config["MAX_CONTENT_LENGTH"] = settings_data["upload_limit_mb"] * 1024 * 1024
    app.extensions["settings_data"] = settings_data
    app.extensions["base_dir"] = base
    app.extensions["engine_versions"] = {}

    manager = TaskManager(upload_dir, engine_resolver=make_engine_resolver(settings_data, base))
    app.extensions["task_manager"] = manager
    watcher = FolderWatcher(settings_data,
                            auto_convert_handler=make_auto_convert_handler(manager, settings_data, base))
    app.extensions["watcher"] = watcher
    watcher.start()
    if settings_data.get("output_dir"):
        manager.registered_dirs.add(str(Path(settings_data["output_dir"])))

    app.register_blueprint(api.bp)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "接口不存在"}), 404
        return "页面不存在", 404

    @app.errorhandler(413)
    def too_large(_error):
        limit = app.extensions["settings_data"]["upload_limit_mb"]
        return jsonify({"error": f"上传内容超过 {limit} MB 上限，可在设置中调整"}), 413

    @app.errorhandler(500)
    def server_error(_error):
        return jsonify({"error": "服务内部错误，请重试或反馈日志"}), 500

    def cleanup_uploads():
        shutil.rmtree(upload_dir, ignore_errors=True)

    if not testing:
        atexit.register(cleanup_uploads)  # 程序退出时清空上传目录（技术方案 4.4）
    log.info("Web 服务就绪：基目录 %s，引擎已检测=%s", base,
             manager.resolve_engine() is not None)
    return app
