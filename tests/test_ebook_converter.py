# -*- coding: utf-8 -*-
"""ebook_converter 的测试。"""

import importlib.util
import io
import subprocess
from pathlib import Path

import pytest

import ebook_converter as ec

fitz_available = importlib.util.find_spec("fitz") is not None


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


class FakePopen:
    """subprocess.Popen 替身：communicate 时可产生输出文件或抛异常。"""

    def __init__(self, returncode=0, stderr="", stdout="", action=None):
        self.returncode = returncode
        self._stderr = stderr
        self._stdout = stdout
        self._action = action
        self._action_fired = False
        self.killed = False

    def communicate(self, timeout=None):
        if self._action is not None and not self._action_fired:
            self._action_fired = True
            self._action()
        return (self._stdout, self._stderr)

    def kill(self):
        self.killed = True


def make_engine_action(dst):
    """返回一个 action：转换“成功”时写出目标文件（2048 字节）。"""

    def action():
        Path(dst).write_bytes(b"x" * 2048)

    return action


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
        monkeypatch.setattr(
            ec.subprocess, "Popen",
            lambda *a, **k: FakePopen(action=make_engine_action(dst)),
        )
        status, msg = ec.convert_file("dummy-engine", src, dst)
        assert status == ec.STATUS_OK

    def test_failed_on_nonzero_exit(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        monkeypatch.setattr(ec.subprocess, "Popen", lambda *a, **k: FakePopen(1, stderr="boom"))
        status, msg = ec.convert_file("dummy-engine", src, tmp_path / "a.epub")
        assert status == ec.STATUS_FAILED
        assert "boom" in msg

    def test_failed_when_no_output_file(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        monkeypatch.setattr(ec.subprocess, "Popen", lambda *a, **k: FakePopen())
        status, msg = ec.convert_file("dummy-engine", src, tmp_path / "a.epub")
        assert status == ec.STATUS_FAILED
        assert "未产生输出" in msg

    def test_failed_when_output_too_small(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"

        def action():
            dst.write_bytes(b"x" * 10)  # 小于 1KB

        monkeypatch.setattr(ec.subprocess, "Popen", lambda *a, **k: FakePopen(action=action))
        status, msg = ec.convert_file("dummy-engine", src, dst)
        assert status == ec.STATUS_FAILED
        assert "10" in msg

    def test_failed_on_timeout(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        monkeypatch.setattr(
            ec.subprocess, "Popen",
            lambda *a, **k: FakePopen(
                action=lambda: (_ for _ in ()).throw(
                    subprocess.TimeoutExpired(cmd="x", timeout=1))),
        )
        status, msg = ec.convert_file("dummy-engine", src, tmp_path / "a.epub")
        assert status == ec.STATUS_FAILED
        assert "超时" in msg

    def test_failed_cleanup_removes_partial_output(self, tmp_path, monkeypatch):
        """转换失败后残缺输出必须被清理，否则下次会被'输出已存在'误跳过。"""
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"

        def action():
            dst.write_bytes(b"x" * 10)  # 残缺输出

        monkeypatch.setattr(ec.subprocess, "Popen", lambda *a, **k: FakePopen(action=action))
        status, _ = ec.convert_file("dummy-engine", src, dst)
        assert status == ec.STATUS_FAILED
        assert not dst.exists()

    def test_keyboard_interrupt_cleans_up_and_reraises(self, tmp_path, monkeypatch):
        """Ctrl+C 中断时：杀掉子进程、清理残缺输出、向上抛出 KeyboardInterrupt。"""
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"

        def action():
            dst.write_bytes(b"partial output")  # 中断前已写出部分内容
            raise KeyboardInterrupt

        fake = FakePopen(action=action)
        monkeypatch.setattr(ec.subprocess, "Popen", lambda *a, **k: fake)
        with pytest.raises(KeyboardInterrupt):
            ec.convert_file("dummy-engine", src, dst)
        assert fake.killed
        assert not dst.exists()

    def test_source_file_untouched(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("内容")
        monkeypatch.setattr(ec.subprocess, "Popen", lambda *a, **k: FakePopen(1, stderr="x"))
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

    def test_duplicate_stem_reports_conflict(self, tmp_path, monkeypatch):
        """a.txt 与 a.epub 同转 mobi 时，第二个必须明确提示重名而不是默默跳过。"""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("x")
        (src / "a.epub").write_text("x")

        monkeypatch.setattr(
            ec, "convert_file",
            lambda engine, s, d: (ec.STATUS_OK, "ok"),
        )
        results = ec.run_conversion(src, "mobi", tmp_path / "out", engine="dummy")

        # 扫描按文件名排序，a.epub 排在 a.txt 前面、先转换
        statuses = {Path(s).name: (st, msg) for s, st, msg in results}
        assert statuses["a.epub"][0] == ec.STATUS_OK
        assert statuses["a.txt"][0] == ec.STATUS_SKIPPED
        assert "重名" in statuses["a.txt"][1]
        assert "a.epub" in statuses["a.txt"][1]

    def test_on_start_and_on_result_callbacks(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("x")
        (src / "b.txt").write_text("x")

        monkeypatch.setattr(
            ec, "convert_file",
            lambda engine, s, d: (ec.STATUS_OK, "ok"),
        )
        started, progress = [], []
        ec.run_conversion(src, "mobi", tmp_path / "out", engine="dummy",
                          on_start=started.append,
                          on_result=lambda s, st, msg: progress.append(Path(s).name))

        assert [f.name for f in started[0]] == ["a.txt", "b.txt"]  # 开始前拿到完整清单
        assert progress == ["a.txt", "b.txt"]  # 每转完一个立即回调

    def test_raises_when_engine_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ec, "find_engine", lambda: None)
        with pytest.raises(ec.EngineNotFoundError):
            ec.run_conversion(tmp_path, "mobi", tmp_path / "out")

    def test_scanned_pdf_warning_added_for_text_target(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        src.mkdir()
        (src / "scan.pdf").write_text("x")
        monkeypatch.setattr(ec, "convert_file", lambda engine, s, d: (ec.STATUS_OK, "ok"))
        monkeypatch.setattr(ec, "pdf_has_text_layer", lambda p, **k: False)

        results = ec.run_conversion(src, "mobi", tmp_path / "out", engine="dummy")
        assert results[0][1] == ec.STATUS_OK
        assert "扫描版 PDF" in results[0][2]

    def test_scanned_pdf_no_warning_for_pdf_target(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        src.mkdir()
        (src / "scan.pdf").write_text("x")
        monkeypatch.setattr(ec, "convert_file", lambda engine, s, d: (ec.STATUS_OK, "ok"))
        monkeypatch.setattr(ec, "pdf_has_text_layer", lambda p, **k: False)

        results = ec.run_conversion(src, "pdf", tmp_path / "out", engine="dummy")
        assert "扫描版" not in results[0][2]

    def test_text_pdf_no_warning(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        src.mkdir()
        (src / "book.pdf").write_text("x")
        monkeypatch.setattr(ec, "convert_file", lambda engine, s, d: (ec.STATUS_OK, "ok"))
        monkeypatch.setattr(ec, "pdf_has_text_layer", lambda p, **k: True)

        results = ec.run_conversion(src, "mobi", tmp_path / "out", engine="dummy")
        assert "扫描版" not in results[0][2]


class FakeStreamPopen:
    """流式读取路径的 Popen 替身：stderr/stdout 为内存流，wait 可定时或超时。

    hang=True 时模拟"转换一直不结束"：未 killed 前 wait 一律抛 TimeoutExpired。
    """

    def __init__(self, returncode=0, stderr="", stdout="", action=None,
                 output_file=None, hang=False):
        self.returncode = returncode
        self.stderr = io.StringIO(stderr)
        self.stdout = io.StringIO(stdout)
        self._action = action
        self._action_fired = False
        self._output_file = output_file
        self._hang = hang
        self.killed = False

    def wait(self, timeout=None):
        if self._hang and not self.killed:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 1)
        if self._action is not None and not self._action_fired:
            self._action_fired = True
            self._action()
        if self._output_file is not None:
            Path(self._output_file).write_bytes(b"x" * 2048)
        return self.returncode

    def kill(self):
        self.killed = True


class TestConvertFileProgress:
    """on_progress 流式路径（M3）：解析 stderr 百分比，行为与默认路径一致。"""

    def test_reports_parsed_percentages_monotonic(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"
        monkeypatch.setattr(
            ec.subprocess, "Popen",
            lambda *a, **k: FakeStreamPopen(stdout="Parsing...\r10%\r5%\r50%\r100%\rdone\n",
                                            output_file=dst),
        )
        seen = []
        status, _ = ec.convert_file("dummy-engine", src, dst, on_progress=seen.append)
        assert status == ec.STATUS_OK
        assert seen == [10, 50, 100]  # 回退的 5% 被忽略

    def test_ok_requires_output_file(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        monkeypatch.setattr(
            ec.subprocess, "Popen",
            lambda *a, **k: FakeStreamPopen(stderr="50%"),
        )
        status, msg = ec.convert_file("dummy-engine", src, tmp_path / "a.epub",
                                      on_progress=lambda pct: None)
        assert status == ec.STATUS_FAILED
        assert "未产生输出" in msg

    def test_ok_with_output_file(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"
        monkeypatch.setattr(
            ec.subprocess, "Popen",
            lambda *a, **k: FakeStreamPopen(output_file=dst),
        )
        status, _ = ec.convert_file("dummy-engine", src, dst, on_progress=lambda pct: None)
        assert status == ec.STATUS_OK

    def test_failed_on_nonzero_exit(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        monkeypatch.setattr(
            ec.subprocess, "Popen",
            lambda *a, **k: FakeStreamPopen(returncode=1, stderr="boom\n"),
        )
        status, msg = ec.convert_file("dummy-engine", src, tmp_path / "a.epub",
                                      on_progress=lambda pct: None)
        assert status == ec.STATUS_FAILED
        assert "boom" in msg

    def test_failed_cleanup_removes_partial_output(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"

        def action():
            dst.write_bytes(b"tiny")  # 残缺输出

        monkeypatch.setattr(
            ec.subprocess, "Popen",
            lambda *a, **k: FakeStreamPopen(action=action),
        )
        status, _ = ec.convert_file("dummy-engine", src, dst, on_progress=lambda pct: None)
        assert status == ec.STATUS_FAILED
        assert not dst.exists()

    def test_timeout_kills_and_cleans_up(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"

        fake = FakeStreamPopen(hang=True, output_file=dst)
        monkeypatch.setattr(ec.subprocess, "Popen", lambda *a, **k: fake)
        monkeypatch.setattr(ec, "CONVERT_TIMEOUT_SECONDS", 1)  # 缩短 deadline 加速测试
        status, msg = ec.convert_file("dummy-engine", src, dst, on_progress=lambda p: None)
        assert status == ec.STATUS_FAILED
        assert "超时" in msg
        assert fake.killed
        assert not dst.exists()

    def test_ignores_non_percentage_lines(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"
        monkeypatch.setattr(
            ec.subprocess, "Popen",
            lambda *a, **k: FakeStreamPopen(stdout="第 1/3 步\n没有百分号的行\n100%\n",
                                            output_file=dst),
        )
        seen = []
        status, _ = ec.convert_file("dummy-engine", src, dst, on_progress=seen.append)
        assert status == ec.STATUS_OK
        assert seen == [100]


class TestConvertFileCancel:
    """cancel_check 取消路径（V1.1 C2）：轮询取消请求，杀进程并清理残缺输出。"""

    def test_cancel_check_stops_process_and_cleans_up(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"
        fake = FakeStreamPopen(hang=True, output_file=dst)
        monkeypatch.setattr(ec.subprocess, "Popen", lambda *a, **k: fake)
        status, msg = ec.convert_file("dummy-engine", src, dst,
                                      on_progress=lambda p: None, cancel_check=lambda: True)
        assert status == ec.STATUS_FAILED
        assert "已取消" in msg
        assert fake.killed
        assert not dst.exists()

    def test_cancel_check_false_runs_to_completion(self, tmp_path, monkeypatch):
        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "a.epub"
        monkeypatch.setattr(ec.subprocess, "Popen",
                            lambda *a, **k: FakeStreamPopen(output_file=dst))
        status, _ = ec.convert_file("dummy-engine", src, dst,
                                    on_progress=lambda p: None, cancel_check=lambda: False)
        assert status == ec.STATUS_OK


def make_text_pdf(path):
    """用 PyMuPDF 生成一个有文字层的 PDF。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(72, 72, 500, 500), "Hello 电子书 text layer " * 20)
    doc.save(path)
    doc.close()


def make_scanned_pdf(path):
    """用 PyMuPDF 生成一个无文字层的“扫描版” PDF（纯图形）。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(100, 100, 400, 400), color=(0, 0, 0), width=2)
    doc.save(path)
    doc.close()


@pytest.mark.skipif(not fitz_available, reason="未安装 PyMuPDF")
class TestPdfTextLayerDetection:
    def test_text_pdf_detected(self, tmp_path):
        pdf = tmp_path / "text.pdf"
        make_text_pdf(pdf)
        assert ec.pdf_has_text_layer(pdf) is True

    def test_scanned_pdf_detected(self, tmp_path):
        pdf = tmp_path / "scan.pdf"
        make_scanned_pdf(pdf)
        assert ec.pdf_has_text_layer(pdf) is False

    def test_missing_file_returns_none(self, tmp_path):
        assert ec.pdf_has_text_layer(tmp_path / "nope.pdf") is None

    def test_missing_dependency_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setitem(__import__("sys").modules, "fitz", None)
        assert ec.pdf_has_text_layer(tmp_path / "any.pdf") is None


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

    @pytest.mark.skipif(not calibre_available() or not fitz_available,
                        reason="本机未安装 Calibre 或 PyMuPDF")
    def test_scanned_pdf_real_detection_warning(self, tmp_path, monkeypatch):
        """真实 Calibre + 真实扫描版 PDF：整条链路应给出扫描版警告。"""
        src = tmp_path / "扫描书.pdf"
        make_scanned_pdf(src)
        monkeypatch.setattr(ec, "convert_file",
                            lambda engine, s, d: (ec.STATUS_OK, "ok"))  # 不真转，只验证警告链路
        results = ec.run_conversion(tmp_path, "mobi", tmp_path / "out",
                                    engine=ec.find_engine())
        assert "扫描版 PDF" in results[0][2]
