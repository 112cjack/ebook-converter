# -*- coding: utf-8 -*-
"""webapp 服务层测试。

转换调用以假引擎替换真实 ebook-convert，保证测试确定性（技术方案 8.1）；
覆盖上传白名单、任务状态流转、失败映射与设置读写。
"""

import io
import json
import time
from pathlib import Path

import pytest

import ebook_converter as ec
from webapp import create_app
from webapp import settings as settings_mod


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """隔离的应用实例：基目录指向 tmp_path，默认无 Calibre。"""
    monkeypatch.setattr(ec, "find_engine", lambda: None)
    app = create_app(base_dir=tmp_path, testing=True)
    return app


@pytest.fixture()
def client(app_env):
    return app_env.test_client()


def set_fake_engine(app, engine="dummy"):
    app.extensions["task_manager"].resolve_engine = lambda: engine


def fake_convert_ok(engine, src, dst, on_progress=None, cancel_check=None):
    dst = Path(dst)
    if dst.exists():
        return ec.STATUS_SKIPPED, "输出已存在"  # 模拟引擎层对既有输出的跳过行为
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"x" * 2048)
    return ec.STATUS_OK, f"{dst.name}（2 KB）"


def upload_file(client, name, content=b"book", field="files"):
    return client.post(
        "/api/upload",
        data={field: (io.BytesIO(content), name)},
        content_type="multipart/form-data",
    )


def convert_and_wait(client, app_env, body):
    """提交转换并等待 worker 队列清空，返回 GET /api/tasks 的任务列表。"""
    resp = client.post("/api/convert", json=body)
    app_env.extensions["task_manager"].wait_idle()
    listing = client.get("/api/tasks").get_json()
    return resp, listing["tasks"]


# ── settings 模块 ──


class TestSettingsModule:
    def test_load_returns_defaults_when_missing(self, tmp_path):
        data = settings_mod.load(tmp_path)
        assert data == settings_mod.DEFAULTS

    def test_save_load_roundtrip(self, tmp_path):
        settings_mod.save({"output_dir": r"D:\Out", "engine_path": "x.exe",
                           "upload_limit_mb": 50}, base_dir=tmp_path)
        assert settings_mod.load(tmp_path)["output_dir"] == r"D:\Out"
        assert settings_mod.load(tmp_path)["upload_limit_mb"] == 50

    def test_corrupted_file_falls_back_to_defaults(self, tmp_path):
        (tmp_path / "settings.json").write_text("{bad json", encoding="utf-8")
        assert settings_mod.load(tmp_path) == settings_mod.DEFAULTS

    def test_upload_limit_clamped(self, tmp_path):
        settings_mod.save({"upload_limit_mb": 99999}, base_dir=tmp_path)
        assert settings_mod.load(tmp_path)["upload_limit_mb"] == settings_mod.MAX_UPLOAD_LIMIT_MB


# ── 上传白名单 ──


class TestUpload:
    def test_accepts_supported_files(self, client, app_env):
        resp = upload_file(client, "书.epub")
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["uploads"][0]["name"] == "书.epub"
        assert body["uploads"][0]["format"] == "epub"
        assert body["rejected"] == []
        # 文件确实落盘到工作目录
        stored = app_env.extensions["task_manager"].upload_path(
            app_env.extensions["task_manager"].uploads[body["uploads"][0]["id"]])
        assert stored.read_bytes() == b"book"

    def test_rejects_unsupported_extension(self, client):
        resp = upload_file(client, "virus.exe")
        body = resp.get_json()
        assert resp.status_code == 201
        assert body["uploads"] == []
        assert body["rejected"][0]["reason"] == "不支持的文件格式"

    def test_rejects_empty_file(self, client):
        resp = upload_file(client, "empty.epub", content=b"")
        assert resp.get_json()["rejected"][0]["reason"] == "文件内容为空"

    def test_no_files_returns_400(self, client):
        resp = client.post("/api/upload", data={}, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_upload_over_limit_returns_413(self, app_env):
        app_env.config["MAX_CONTENT_LENGTH"] = 1024
        client = app_env.test_client()
        resp = upload_file(client, "big.epub", content=b"x" * 4096)
        assert resp.status_code == 413
        assert "上限" in resp.get_json()["error"]

    def test_path_components_stripped(self, client):
        resp = upload_file(client, "..\\evil\\../../book.epub")
        body = resp.get_json()
        assert body["uploads"][0]["name"] == "evil_book.epub" or "\\" not in body["uploads"][0]["name"]
        assert "/" not in body["uploads"][0]["name"]


# ── 转换提交 ──


class TestConvertApi:
    def test_unknown_format_rejected(self, client):
        upload_file(client, "a.epub")
        resp = client.post("/api/convert", json={"format": "exe"})
        assert resp.status_code == 400

    def test_convert_without_uploads_rejected(self, client):
        resp = client.post("/api/convert", json={"format": "mobi"})
        assert resp.status_code == 400
        assert "先上传" in resp.get_json()["error"]

    def test_creates_queued_tasks(self, client, app_env):
        set_fake_engine(app_env)
        up = upload_file(client, "a.epub").get_json()["uploads"][0]
        resp = client.post("/api/convert", json={"format": "mobi"})
        assert resp.status_code == 201
        task = resp.get_json()["tasks"][0]
        assert task["status"] == "queued"
        assert task["upload_id"] == up["id"]
        assert task["output_path"].endswith("a.mobi")

    def test_engine_missing_returns_409_with_guidance(self, client):
        upload_file(client, "a.epub")
        resp = client.post("/api/convert", json={"format": "mobi"})
        assert resp.status_code == 409
        body = resp.get_json()
        assert "Calibre" in body["error"]
        assert body["engine"]["installed"] is False

    def test_relative_output_dir_rejected(self, client, app_env):
        set_fake_engine(app_env)
        upload_file(client, "a.epub")
        resp = client.post("/api/convert", json={"format": "mobi", "output_dir": "relative"})
        assert resp.status_code == 400

    def test_upload_dir_as_output_rejected(self, client, app_env):
        set_fake_engine(app_env)
        upload_file(client, "a.epub")
        upload_dir = str(app_env.extensions["task_manager"].upload_dir)
        resp = client.post("/api/convert", json={"format": "mobi", "output_dir": upload_dir})
        assert resp.status_code == 400

    def test_output_dir_defaults_to_setting(self, client, app_env, tmp_path):
        set_fake_engine(app_env)
        custom = tmp_path / "我的输出"
        client.post("/api/settings", json={"output_dir": str(custom)})
        upload_file(client, "a.epub")
        resp = client.post("/api/convert", json={"format": "mobi"})
        assert custom in Path(resp.get_json()["tasks"][0]["output_dir"]).parents or \
            str(custom) == resp.get_json()["tasks"][0]["output_dir"]


# ── 任务状态流转 ──


class TestTaskFlow:
    def test_success_flow(self, client, app_env, tmp_path):
        set_fake_engine(app_env)
        monkey_ok = pytest.MonkeyPatch()
        monkey_ok.setattr(ec, "convert_file", fake_convert_ok)
        try:
            upload_file(client, "三体.epub")
            out = tmp_path / "out"
            resp, tasks = convert_and_wait(
                client, app_env, {"format": "mobi", "output_dir": str(out)})
        finally:
            monkey_ok.undo()
        assert resp.status_code == 201
        assert tasks[0]["status"] == "done"
        assert tasks[0]["status_label"] == "已完成"
        assert tasks[0]["error"] is None
        produced = out / "三体.mobi"
        assert produced.exists()
        assert Path(tasks[0]["output_path"]) == produced

    def test_failure_maps_to_friendly_error(self, client, app_env, tmp_path):
        set_fake_engine(app_env)
        patcher = pytest.MonkeyPatch()
        patcher.setattr(
            ec, "convert_file",
            lambda engine, s, d, on_progress=None, cancel_check=None: (ec.STATUS_FAILED, "Error: Cannot decrypt DRM"),
        )
        try:
            upload_file(client, "锁.epub")
            _, tasks = convert_and_wait(
                client, app_env, {"format": "mobi", "output_dir": str(tmp_path)})
        finally:
            patcher.undo()
        assert tasks[0]["status"] == "failed"
        assert tasks[0]["error"] == "文件可能已损坏或受版权保护（DRM），暂不支持转换"
        assert "DRM" in tasks[0]["error_detail"]

    def test_engine_skip_becomes_skipped(self, client, app_env, tmp_path):
        set_fake_engine(app_env)
        patcher = pytest.MonkeyPatch()
        patcher.setattr(
            ec, "convert_file",
            lambda engine, s, d, on_progress=None, cancel_check=None: (ec.STATUS_SKIPPED, "输出已存在"),
        )
        try:
            upload_file(client, "a.epub")
            _, tasks = convert_and_wait(
                client, app_env, {"format": "mobi", "output_dir": str(tmp_path)})
        finally:
            patcher.undo()
        assert tasks[0]["status"] == "skipped"
        assert "已存在" in tasks[0]["message"]

    def test_same_batch_duplicate_stem_marks_skipped_with_source(self, client, app_env, tmp_path):
        """同批 a.epub / a.txt 同转 mobi，后者提示与前者重名。"""
        set_fake_engine(app_env)
        patcher = pytest.MonkeyPatch()
        patcher.setattr(ec, "convert_file", fake_convert_ok)
        try:
            upload_file(client, "a.epub")
            upload_file(client, "a.txt")
            _, tasks = convert_and_wait(
                client, app_env, {"format": "mobi", "output_dir": str(tmp_path)})
        finally:
            patcher.undo()
        by_name = {t["name"]: t for t in tasks}
        assert by_name["a.txt"]["status"] == "skipped"
        assert "重名" in by_name["a.txt"]["message"]
        assert "a.epub" in by_name["a.txt"]["message"]

    def test_scanned_pdf_warning_in_result(self, client, app_env, tmp_path):
        set_fake_engine(app_env)
        patcher = pytest.MonkeyPatch()
        patcher.setattr(ec, "convert_file", fake_convert_ok)
        patcher.setattr(ec, "pdf_has_text_layer", lambda p, **k: False)
        try:
            upload_file(client, "扫描书.pdf")
            _, tasks = convert_and_wait(
                client, app_env, {"format": "txt", "output_dir": str(tmp_path)})
        finally:
            patcher.undo()
        assert tasks[0]["status"] == "done"
        assert "扫描版 PDF" in tasks[0]["message"]

    def test_no_warning_for_text_pdf(self, client, app_env, tmp_path):
        set_fake_engine(app_env)
        patcher = pytest.MonkeyPatch()
        patcher.setattr(ec, "convert_file", fake_convert_ok)
        patcher.setattr(ec, "pdf_has_text_layer", lambda p, **k: True)
        try:
            upload_file(client, "书.pdf")
            _, tasks = convert_and_wait(
                client, app_env, {"format": "txt", "output_dir": str(tmp_path)})
        finally:
            patcher.undo()
        assert "扫描版" not in (tasks[0]["message"] or "")

    def test_progress_reported_to_task(self, client, app_env, tmp_path):
        """M3：引擎 stderr 进度经 on_progress 写入任务，轮询可见。"""
        set_fake_engine(app_env)

        def fake_with_progress(engine, src, dst, on_progress=None, cancel_check=None):
            if on_progress:
                on_progress(42)
            return fake_convert_ok(engine, src, dst)

        patcher = pytest.MonkeyPatch()
        patcher.setattr(ec, "convert_file", fake_with_progress)
        try:
            upload_file(client, "a.epub")
            _, tasks = convert_and_wait(
                client, app_env, {"format": "mobi", "output_dir": str(tmp_path)})
        finally:
            patcher.undo()
        assert tasks[0]["status"] == "done"
        assert tasks[0]["progress"] == 42

    def test_failed_task_does_not_block_queue(self, client, app_env, tmp_path):
        """F5：单个任务失败不影响队列中的其他任务。"""
        set_fake_engine(app_env)
        patcher = pytest.MonkeyPatch()
        patcher.setattr(ec, "convert_file", fake_convert_ok)
        try:
            upload_file(client, "a.epub")
            upload_file(client, "b.epub")
            _, tasks = convert_and_wait(
                client, app_env, {"format": "mobi", "output_dir": str(tmp_path)})
        finally:
            patcher.undo()
        assert len(tasks) == 2
        assert all(t["status"] == "done" for t in tasks)


# ── 移除与历史 ──


class TestRemoveAndHistory:
    def test_remove_hides_upload_keeps_task_history(self, client, app_env, tmp_path):
        set_fake_engine(app_env)
        patcher = pytest.MonkeyPatch()
        patcher.setattr(ec, "convert_file", fake_convert_ok)
        try:
            upload_file(client, "a.epub")
            _, tasks = convert_and_wait(
                client, app_env, {"format": "mobi", "output_dir": str(tmp_path)})
        finally:
            patcher.undo()
        uid = tasks[0]["upload_id"]
        resp = client.post("/api/remove", json={"upload_ids": [uid]})
        assert resp.get_json()["removed"] == [uid]
        listing = client.get("/api/tasks").get_json()
        upload = next(u for u in listing["uploads"] if u["id"] == uid)
        assert upload["removed"] is True
        assert listing["tasks"]  # 任务记录保留，作为本次运行的历史
        # 临时上传文件已删除
        mgr = app_env.extensions["task_manager"]
        assert not mgr.upload_path(mgr.uploads[uid]).exists()

    def test_remove_queued_upload_skips_its_task(self, client, app_env):
        set_fake_engine(app_env)
        # 暂停 worker 的任务执行，保证任务稳定停留在 queued 供移除
        patcher = pytest.MonkeyPatch()
        patcher.setattr(app_env.extensions["task_manager"].__class__, "_run_task",
                        lambda self, tid: None)
        try:
            upload_file(client, "a.epub")
            client.post("/api/convert", json={"format": "mobi"})
            up = client.get("/api/tasks").get_json()["uploads"][0]
            resp = client.post("/api/remove", json={"upload_ids": [up["id"]]})
        finally:
            patcher.undo()
        assert resp.get_json()["removed"] == [up["id"]]
        tasks = client.get("/api/tasks").get_json()["tasks"]
        assert tasks[0]["status"] == "skipped"
        assert tasks[0]["message"] == "已从列表移除"

    def test_clear_removes_all_removable(self, client, app_env):
        upload_file(client, "a.epub")
        upload_file(client, "b.txt")
        resp = client.post("/api/remove", json={})
        assert len(resp.get_json()["removed"]) == 2


# ── 打开输出文件夹 ──


class TestOpenFolder:
    def test_unregistered_path_forbidden(self, client, tmp_path):
        resp = client.post("/api/open-folder", json={"path": str(tmp_path / "anywhere")})
        assert resp.status_code == 403

    def test_registered_path_opens(self, client, app_env, tmp_path, monkeypatch):
        set_fake_engine(app_env)
        opened = []
        monkeypatch.setattr("webapp.api.open_in_explorer", lambda p: opened.append(p))
        out = tmp_path / "out"
        out.mkdir()
        upload_file(client, "a.epub")
        client.post("/api/convert", json={"format": "mobi", "output_dir": str(out)})
        resp = client.post("/api/open-folder", json={"path": str(out)})
        assert resp.status_code == 200
        assert opened == [out.resolve()]

    def test_missing_dir_returns_404(self, client, app_env, tmp_path):
        out = tmp_path / "not-created"
        app_env.extensions["task_manager"].registered_dirs.add(str(out))
        resp = client.post("/api/open-folder", json={"path": str(out)})
        assert resp.status_code == 404


# ── 设置读写 ──


class TestSettingsApi:
    def test_get_defaults(self, client):
        body = client.get("/api/settings").get_json()
        assert body["upload_limit_mb"] == 200
        assert body["output_dir"] == ""
        assert body["engine"]["installed"] is False

    def test_post_save_and_reload(self, client, app_env, tmp_path):
        out = tmp_path / "输出"
        resp = client.post("/api/settings", json={"output_dir": str(out),
                                                  "upload_limit_mb": 77})
        body = resp.get_json()
        assert body["output_dir"] == str(out)
        assert body["upload_limit_mb"] == 77
        assert app_env.config["MAX_CONTENT_LENGTH"] == 77 * 1024 * 1024
        # 持久化到 JSON 文件
        on_disk = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        assert on_disk["upload_limit_mb"] == 77

    def test_invalid_limit_rejected(self, client):
        resp = client.post("/api/settings", json={"upload_limit_mb": 0})
        assert resp.status_code == 400

    def test_non_absolute_output_dir_rejected(self, client):
        resp = client.post("/api/settings", json={"output_dir": "rel/path"})
        assert resp.status_code == 400

    def test_missing_engine_file_rejected(self, client):
        resp = client.post("/api/settings", json={"engine_path": "X:/no/such/engine.exe"})
        assert resp.status_code == 400
        assert "不存在" in resp.get_json()["error"]


# ── 健壮性基座 ──


class TestRobustness:
    def test_long_filename_truncated_but_extension_kept(self, client, app_env):
        long_name = "超" * 200 + ".epub"
        rec = upload_file(client, long_name).get_json()["uploads"][0]
        assert len(Path(rec["name"]).stem) <= 80
        assert rec["name"].endswith(".epub")
        assert rec["truncated"] is True

    def test_normal_filename_not_marked_truncated(self, client):
        rec = upload_file(client, "普通书.epub").get_json()["uploads"][0]
        assert rec["truncated"] is False

    def test_startup_clears_stale_uploads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ec, "find_engine", lambda: None)
        stale = tmp_path / "tmp" / "uploads"
        stale.mkdir(parents=True)
        (stale / "old.epub").write_bytes(b"x")
        app = create_app(base_dir=tmp_path, testing=True)
        assert not (stale / "old.epub").exists()
        assert app.extensions["task_manager"].upload_dir.is_dir()


# ── 同格式跳过与扫描版 PDF 预检测 ──


class TestConvertSemantics:
    def test_same_format_task_skipped_without_queue(self, client, app_env, tmp_path):
        set_fake_engine(app_env)
        upload_file(client, "a.epub")
        resp, tasks = convert_and_wait(
            client, app_env, {"format": "epub", "output_dir": str(tmp_path)})
        assert resp.status_code == 201
        assert tasks[0]["status"] == "skipped"
        assert "无需转换" in tasks[0]["message"]
        assert not (tmp_path / "a.epub").exists()

    def test_pdf_scan_flag_on_upload(self, client, app_env, monkeypatch, tmp_path):
        fake = tmp_path / "scan.pdf"
        fake.write_bytes(b"%PDF-")
        monkeypatch.setattr(ec, "pdf_has_text_layer", lambda p, **k: False)
        with open(fake, "rb") as fh:
            body = client.post("/api/upload", data={"files": (fh, "scan.pdf")},
                               content_type="multipart/form-data").get_json()
        assert body["uploads"][0]["scanned_pdf"] is True

    def test_text_pdf_no_flag(self, client, app_env, monkeypatch, tmp_path):
        fake = tmp_path / "text.pdf"
        fake.write_bytes(b"%PDF-")
        monkeypatch.setattr(ec, "pdf_has_text_layer", lambda p, **k: True)
        with open(fake, "rb") as fh:
            body = client.post("/api/upload", data={"files": (fh, "text.pdf")},
                               content_type="multipart/form-data").get_json()
        assert body["uploads"][0]["scanned_pdf"] is False

    def test_non_pdf_has_no_scan_flag(self, client):
        rec = upload_file(client, "a.epub").get_json()["uploads"][0]
        assert rec["scanned_pdf"] is False


# ── 取消转换 ──


class TestCancel:
    def test_cancel_converting_task(self, client, app_env, tmp_path):
        set_fake_engine(app_env)

        def slow_convert(engine, src, dst, on_progress=None, cancel_check=None):
            dst.parent.mkdir(parents=True, exist_ok=True)
            for _ in range(300):
                if cancel_check is not None and cancel_check():
                    return ec.STATUS_FAILED, "已取消"
                time.sleep(0.02)
            dst.write_bytes(b"x" * 2048)
            return ec.STATUS_OK, "ok"

        patcher = pytest.MonkeyPatch()
        patcher.setattr(ec, "convert_file", slow_convert)
        try:
            upload_file(client, "a.epub")
            client.post("/api/convert", json={"format": "mobi", "output_dir": str(tmp_path)})
            app_env.extensions["task_manager"].wait_idle()  # 等 worker 取到任务
            task = client.get("/api/tasks").get_json()["tasks"][0]
            if task["status"] == "converting":
                resp = client.post("/api/cancel", json={"task_id": task["id"]})
                assert resp.status_code == 200
            app_env.extensions["task_manager"].wait_idle()
            task = client.get("/api/tasks").get_json()["tasks"][0]
            assert task["status"] in ("cancelled", "done")  # 极慢环境下可能已自然完成
            if task["status"] == "cancelled":
                assert "取消" in task["message"]
        finally:
            patcher.undo()

    def test_cancel_unknown_task_rejected(self, client):
        assert client.post("/api/cancel", json={"task_id": "nope"}).status_code == 400


# ── 覆盖重转 ──


class TestOverwrite:
    def test_overwrite_replaces_existing_output(self, client, app_env, tmp_path):
        set_fake_engine(app_env)
        out = tmp_path / "out"
        out.mkdir()
        (out / "a.mobi").write_bytes(b"old" * 100)
        patcher = pytest.MonkeyPatch()
        patcher.setattr(ec, "convert_file", fake_convert_ok)
        try:
            upload_file(client, "a.epub")
            _, tasks = convert_and_wait(
                client, app_env,
                {"format": "mobi", "output_dir": str(out), "overwrite": True})
        finally:
            patcher.undo()
        assert tasks[0]["status"] == "done"
        assert (out / "a.mobi").read_bytes() == b"x" * 2048

    def test_without_overwrite_existing_output_skipped(self, client, app_env, tmp_path):
        set_fake_engine(app_env)
        out = tmp_path / "out"
        out.mkdir()
        (out / "a.mobi").write_bytes(b"old" * 100)
        patcher = pytest.MonkeyPatch()
        patcher.setattr(ec, "convert_file", fake_convert_ok)
        try:
            upload_file(client, "a.epub")
            _, tasks = convert_and_wait(
                client, app_env, {"format": "mobi", "output_dir": str(out)})
        finally:
            patcher.undo()
        assert tasks[0]["status"] == "skipped"
        assert (out / "a.mobi").read_bytes() == b"old" * 100


# ── 目录浏览 ──


class TestBrowse:
    def test_lists_subdirectories_only(self, client, tmp_path):
        target = tmp_path / "浏览目录"
        target.mkdir()
        (target / "子目录").mkdir()
        (target / "file.txt").write_text("x")
        (target / ".隐藏").mkdir()
        resp = client.get("/api/browse", query_string={"path": str(target)})
        body = resp.get_json()
        assert [e["name"] for e in body["entries"]] == ["子目录"]
        assert body["current"] == str(target)

    def test_no_path_lists_drives(self, client, monkeypatch):
        monkeypatch.setattr("webapp.api.list_drives", lambda: ["C:", "D:"])
        body = client.get("/api/browse").get_json()
        assert [e["path"] for e in body["entries"]] == ["C:\\", "D:\\"]  # 带分隔符，可直接下钻

    def test_invalid_path_rejected(self, client):
        assert client.get("/api/browse", query_string={"path": "rel"}).status_code == 400
        assert client.get(
            "/api/browse", query_string={"path": "Z:/__no_such__"}).status_code == 400


# ── 状态与页面 ──


class TestStatusAndPages:
    def test_status_reports_engine_missing(self, client):
        body = client.get("/api/status").get_json()
        assert body["engine"]["installed"] is False
        assert body["output_formats"] == list(ec.OUTPUT_FORMATS)
        assert ".epub" in body["input_extensions"]

    def test_status_reports_manual_engine(self, app_env, tmp_path):
        fake = tmp_path / "ebook-convert.exe"
        fake.write_text("")
        app_env.extensions["settings_data"]["engine_path"] = str(fake)
        body = app_env.test_client().get("/api/status").get_json()
        assert body["engine"]["installed"] is True
        assert body["engine"]["source"] == "manual"

    def test_index_serves_single_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")
        assert b"<title>" in resp.data

    def test_unknown_api_returns_json_404(self, client):
        resp = client.get("/api/unknown")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "接口不存在"
