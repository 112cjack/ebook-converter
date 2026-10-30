# -*- coding: utf-8 -*-
"""ebook_converter MVP 的测试。"""

import shutil
import subprocess
from pathlib import Path

import pytest

import ebook_converter as ec


class TestFormatTables:
    def test_input_extensions_cover_common_formats(self):
        for ext in (".epub", ".mobi", ".azw3", ".pdf", ".txt", ".docx", ".rtf", ".fb2", ".cbz"):
            assert ext in ec.INPUT_EXTENSIONS

    def test_input_extensions_are_lowercase(self):
        assert all(ext == ext.lower() for ext in ec.INPUT_EXTENSIONS)

    def test_output_formats_menu(self):
        for fmt in ("epub", "mobi", "azw3", "pdf", "txt"):
            assert fmt in ec.OUTPUT_FORMATS


class TestScanFolder:
    def test_finds_supported_files_ignoring_case(self, tmp_path):
        (tmp_path / "a.epub").write_text("x")
        (tmp_path / "b.MOBI").write_text("x")
        (tmp_path / "c.txt").write_text("x")
        found = ec.scan_folder(tmp_path)
        assert [f.name for f in found] == ["a.epub", "b.MOBI", "c.txt"]

    def test_skips_unsupported_and_hidden_and_temp(self, tmp_path):
        (tmp_path / "a.epub").write_text("x")
        (tmp_path / "skip.xyz").write_text("x")
        (tmp_path / ".hidden.epub").write_text("x")
        (tmp_path / "~$temp.docx").write_text("x")
        (tmp_path / "subdir").mkdir()
        found = ec.scan_folder(tmp_path)
        assert [f.name for f in found] == ["a.epub"]

    def test_folder_path_returned_sorted(self, tmp_path):
        for name in ("c.txt", "a.txt", "b.txt"):
            (tmp_path / name).write_text("x")
        assert [f.name for f in ec.scan_folder(tmp_path)] == ["a.txt", "b.txt", "c.txt"]


class FakeProc:
    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


class TestConvertFile:
    def test_skips_when_output_exists(self, tmp_path):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"
        dst.write_bytes(b"x" * 2048)
        status, msg = ec.convert_file("dummy-engine", src, dst)
        assert status == ec.STATUS_SKIPPED
        assert "已存在" in msg

    def test_ok_when_engine_produces_output(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"

        def fake_run(cmd, **kwargs):
            Path(cmd[2]).write_bytes(b"x" * 2048)
            return FakeProc()

        monkeypatch.setattr(ec.subprocess, "run", fake_run)
        status, msg = ec.convert_file("dummy-engine", src, dst)
        assert status == ec.STATUS_OK

    def test_failed_on_nonzero_exit(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        monkeypatch.setattr(ec.subprocess, "run", lambda *a, **k: FakeProc(1, stderr="boom"))
        status, msg = ec.convert_file("dummy-engine", src, tmp_path / "a.epub")
        assert status == ec.STATUS_FAILED
        assert "boom" in msg

    def test_failed_when_no_output_file(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        monkeypatch.setattr(ec.subprocess, "run", lambda *a, **k: FakeProc())
        status, msg = ec.convert_file("dummy-engine", src, tmp_path / "a.epub")
        assert status == ec.STATUS_FAILED
        assert "未产生输出" in msg

    def test_failed_when_output_too_small(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"

        def fake_run(cmd, **kwargs):
            Path(cmd[2]).write_bytes(b"x" * 10)  # 小于 1KB
            return FakeProc()

        monkeypatch.setattr(ec.subprocess, "run", fake_run)
        status, msg = ec.convert_file("dummy-engine", src, dst)
        assert status == ec.STATUS_FAILED
        assert "10" in msg

    def test_failed_on_timeout(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        monkeypatch.setattr(
            ec.subprocess, "run",
            lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="x", timeout=1)),
        )
        status, msg = ec.convert_file("dummy-engine", src, tmp_path / "a.epub")
        assert status == ec.STATUS_FAILED
        assert "超时" in msg

    def test_source_file_untouched(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("内容")
        monkeypatch.setattr(ec.subprocess, "run", lambda *a, **k: FakeProc(1, stderr="x"))
        ec.convert_file("dummy-engine", src, tmp_path / "a.epub")
        assert src.read_text() == "内容"


class TestFindEngine:
    def test_uses_path_hit(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ec.shutil, "which", lambda name: str(tmp_path / "ebook-convert"))
        assert ec.find_engine() == tmp_path / "ebook-convert"

    def test_falls_back_to_install_location(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ec.shutil, "which", lambda name: None)
        fake = tmp_path / "ebook-convert.exe"
        fake.write_text("")
        monkeypatch.setattr(ec, "CALIBRE_FALLBACK_PATHS", [fake])
        assert ec.find_engine() == fake

    def test_returns_none_when_missing(self, monkeypatch):
        monkeypatch.setattr(ec.shutil, "which", lambda name: None)
        monkeypatch.setattr(ec, "CALIBRE_FALLBACK_PATHS", [])
        assert ec.find_engine() is None


class TestRunConversion:
    def test_converts_all_supported_files_to_target_format(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("x")
        (src / "b.epub").write_text("x")
        (src / "c.xyz").write_text("x")
        out = tmp_path / "out"

        recorded = []

        def fake_convert(engine, s, d):
            recorded.append((engine, Path(s).name, Path(d)))
            d.parent.mkdir(parents=True, exist_ok=True)
            d.write_bytes(b"x" * 2048)
            return ec.STATUS_OK, "ok"

        monkeypatch.setattr(ec, "convert_file", fake_convert)
        results = ec.run_conversion(src, "mobi", out, engine="dummy")

        assert [Path(s).name for s, _, _ in results] == ["a.txt", "b.epub"]
        assert all(d.suffix == ".mobi" and d.parent == out for _, _, d in recorded)

    def test_raises_when_engine_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ec, "find_engine", lambda: None)
        with pytest.raises(ec.EngineNotFoundError):
            ec.run_conversion(tmp_path, "mobi", tmp_path / "out")


def calibre_available():
    return ec.find_engine() is not None


class TestRealConversion:
    @pytest.mark.skipif(not calibre_available(), reason="本机未安装 Calibre")
    def test_txt_to_epub_with_real_calibre(self, tmp_path):
        src = tmp_path / "示例书籍.txt"
        src.write_text("第一章 起点\n\n" + "这是一段用于验证转换的中文正文。" * 30 + "\n",
                       encoding="utf-8")
        status, msg = ec.convert_file(ec.find_engine(), src, tmp_path / "示例书籍.epub")
        assert status == ec.STATUS_OK, msg
        assert (tmp_path / "示例书籍.epub").stat().st_size >= ec.MIN_OUTPUT_BYTES
