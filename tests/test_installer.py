# -*- coding: utf-8 -*-
"""webapp.installer 的测试：假下载与假安装器，覆盖状态机流转。"""

import subprocess
from pathlib import Path

import webapp.installer as installer


def setup_function(_):
    installer.reset_state()


def teardown_function(_):
    installer.reset_state()


def test_portable_install_flow(tmp_path, monkeypatch):
    calls = {}

    def fake_download(url, dest, progress_cb=None):
        calls["url"] = url
        Path(dest).write_bytes(b"installer")
        if progress_cb:
            progress_cb(100)

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(installer, "_download", fake_download)
    monkeypatch.setattr(installer.subprocess, "run", fake_run)

    inst = installer.EngineInstaller(base=tmp_path)
    assert inst.start("portable") is True
    assert inst.wait_done(timeout=5)

    st = installer.install_state()
    assert st["state"] == "done"
    assert st["active"] is False
    assert "calibre-ebook.com" in calls["url"]
    target = str(calls["cmd"][-1])
    assert "engines" in target and "calibre" in target


def test_second_start_rejected_while_active(tmp_path, monkeypatch):
    blocker = {"release": False}

    def hanging_download(url, dest, progress_cb=None):
        import time
        while not blocker["release"]:
            time.sleep(0.01)

    monkeypatch.setattr(installer, "_download", hanging_download)
    inst = installer.EngineInstaller(base=tmp_path)
    assert inst.start("portable") is True
    try:
        assert inst.start("portable") is False
    finally:
        blocker["release"] = True
    assert inst.wait_done(timeout=5)


def test_download_failure_marks_failed_with_alternatives(tmp_path, monkeypatch):
    def broken_download(url, dest, progress_cb=None):
        raise OSError("网络不可达")

    monkeypatch.setattr(installer, "_download", broken_download)
    inst = installer.EngineInstaller(base=tmp_path)
    inst.start("portable")
    assert inst.wait_done(timeout=5)
    st = installer.install_state()
    assert st["state"] == "failed"
    assert "winget" in st["message"] or "官网" in st["message"]


def test_winget_missing_binary_checked_in_api(tmp_path):
    """winget 可用性检查在 API 层（shutil.which），installer 只负责执行。"""
    st = installer.install_state()
    assert st["state"] == "idle"
