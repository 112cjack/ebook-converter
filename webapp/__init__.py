# -*- coding: utf-8 -*-
"""Web 服务层：Flask 应用工厂、REST 路由、任务队列与设置读写。

目录结构遵循《电子书转换器技术方案》第 6 章；
启动方式见 app.py（python -m webapp.app）。
"""

import atexit
import shutil
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import ebook_converter as ec

from . import api, settings
from .tasks import TaskManager


def make_engine_resolver(settings_data):
    """引擎解析：设置中手动指定的路径优先，其次自动探测（技术方案 3.2）。"""
    def resolve():
        manual = str(settings_data.get("engine_path") or "").strip()
        if manual:
            path = Path(manual)
            if path.is_file():
                return path
        return ec.find_engine()
    return resolve


def create_app(base_dir=None, testing=False):
    """构建 Flask 应用：装配设置、任务管理器、路由与错误处理。"""
    base = Path(base_dir) if base_dir else settings.base_dir()
    upload_dir = base / "tmp" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, static_folder="static", static_url_path="")
    app.config["TESTING"] = testing

    settings_data = settings.load(base)
    app.config["MAX_CONTENT_LENGTH"] = settings_data["upload_limit_mb"] * 1024 * 1024
    app.extensions["settings_data"] = settings_data
    app.extensions["base_dir"] = base
    app.extensions["engine_versions"] = {}

    manager = TaskManager(upload_dir, engine_resolver=make_engine_resolver(settings_data))
    app.extensions["task_manager"] = manager
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
    return app
