# -*- coding: utf-8 -*-
"""webapp.installer 的测试：假下载与假安装器，覆盖状态机流转。"""

import subprocess
from pathlib import Path

import pytest

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


# ── 本地安装包（mode=local）──


def test_local_install_uses_package_without_download(tmp_path, monkeypatch):
    calls = {}

    def ban_download(*a, **k):
        raise AssertionError("local 模式不得下载")

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    pkg = tmp_path / "Calibre-Portable.exe"
    pkg.write_bytes(b"x" * (2 * 1024 * 1024))
    monkeypatch.setattr(installer, "_download", ban_download)
    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    inst = installer.EngineInstaller(base=tmp_path)
    assert inst.start("local", package_path=str(pkg)) is True
    assert inst.wait_done(timeout=5)
    st = installer.install_state()
    assert st["state"] == "done"
    assert calls["cmd"][0] == str(pkg)
    assert "engines" in str(calls["cmd"][-1])


def test_local_bad_package_fails_no_download(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "_download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no dl")))

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stderr="bad")

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    pkg = tmp_path / "bad.exe"
    pkg.write_bytes(b"x" * (2 * 1024 * 1024))
    inst = installer.EngineInstaller(base=tmp_path)
    inst.start("local", package_path=str(pkg))
    assert inst.wait_done(timeout=5)
    st = installer.install_state()
    assert st["state"] == "failed"
    assert "无效" in st["message"] or "失败" in st["message"] or "bad" in st["message"]


def test_local_requires_package_path(tmp_path):
    inst = installer.EngineInstaller(base=tmp_path)
    with pytest.raises(ValueError):
        inst.start("local")


def test_unknown_mode_rejected(tmp_path):
    inst = installer.EngineInstaller(base=tmp_path)
    with pytest.raises(ValueError):
        inst.start("carrier-pigeon")


def test_local_too_small_package_fails_without_download(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "_download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no dl")))
    pkg = tmp_path / "tiny.exe"
    pkg.write_bytes(b"x" * 1024)
    inst = installer.EngineInstaller(base=tmp_path)
    inst.start("local", package_path=str(pkg))
    assert inst.wait_done(timeout=5)
    st = installer.install_state()
    assert st["state"] == "failed"
    assert "无效" in st["message"]


def test_local_non_exe_suffix_fails_without_download(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "_download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no dl")))
    pkg = tmp_path / "Calibre.zip"
    pkg.write_bytes(b"x" * (2 * 1024 * 1024))
    inst = installer.EngineInstaller(base=tmp_path)
    inst.start("local", package_path=str(pkg))
    assert inst.wait_done(timeout=5)
    st = installer.install_state()
    assert st["state"] == "failed"
    assert "无效" in st["message"]


def test_local_failure_cleans_uploaded_copy(tmp_path, monkeypatch):
    """失败时清理落在 base/tmp 的上传副本，避免残留上百 MB 安装包。"""
    pkg = tmp_path / "tmp" / "calibre-local-deadbeef.exe"
    pkg.parent.mkdir(parents=True)
    pkg.write_bytes(b"x" * (2 * 1024 * 1024))
    monkeypatch.setattr(installer.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stderr="bad"))
    inst = installer.EngineInstaller(base=tmp_path)
    inst.start("local", package_path=str(pkg))
    assert inst.wait_done(timeout=5)
    assert installer.install_state()["state"] == "failed"
    assert not pkg.exists()


def test_local_success_cleans_uploaded_copy(tmp_path, monkeypatch):
    pkg = tmp_path / "tmp" / "calibre-local-cafebabe.exe"
    pkg.parent.mkdir(parents=True)
    pkg.write_bytes(b"x" * (2 * 1024 * 1024))
    monkeypatch.setattr(installer.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0))
    inst = installer.EngineInstaller(base=tmp_path)
    inst.start("local", package_path=str(pkg))
    assert inst.wait_done(timeout=5)
    assert installer.install_state()["state"] == "done"
    assert not pkg.exists()
