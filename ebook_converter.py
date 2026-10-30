# -*- coding: utf-8 -*-
"""电子书格式转换器

把一个文件夹里的电子书批量转换成用户选择的目标格式。
转换引擎使用 Calibre 自带的 ebook-convert，输入格式覆盖
epub / mobi / azw3 / pdf / docx / rtf / fb2 / cbz / chm / txt 等。

用法：
    python ebook_converter.py                      # 交互式：选文件夹、选格式
    python ebook_converter.py <文件夹> -f mobi     # 命令行直接指定
    python ebook_converter.py <文件夹> -f epub -o <输出目录>

只扫描文件夹第一层，输出目录默认为 <源文件夹>\\converted。
源文件永不删除/修改；转换失败或被中断时，残缺的输出文件会被清理。
"""

import argparse
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

# Calibre 官方支持的输入格式（https://manual.calibre-ebook.com/conversion.html）
INPUT_EXTENSIONS = {
    ".azw", ".azw3", ".azw4", ".cbz", ".cbr", ".cbc", ".chm",
    ".djvu", ".docx", ".epub", ".fb2", ".fbz", ".html", ".htmlz",
    ".lit", ".lrf", ".mobi", ".odt", ".pdb", ".pdf", ".pml",
    ".prc", ".rb", ".rtf", ".snb", ".tcr", ".txt", ".txtz",
}

# 交互菜单提供的常用目标格式（均为 Calibre 官方支持的输出格式）
OUTPUT_FORMATS = ["epub", "mobi", "azw3", "pdf", "txt", "docx", "rtf", "fb2", "odt", "htmlz"]

CALIBRE_EXE = "ebook-convert.exe" if sys.platform == "win32" else "ebook-convert"
CALIBRE_FALLBACK_PATHS = [
    Path("C:/Program Files/Calibre2") / CALIBRE_EXE,
    Path("C:/Program Files (x86)/Calibre2") / CALIBRE_EXE,
]

# 输出文件小于 1KB 视为转换失败（沿用旧项目 kindle-auto-convert 的校验规则）
MIN_OUTPUT_BYTES = 1024
CONVERT_TIMEOUT_SECONDS = 1800

# 扫描版 PDF 检测的采样页数（只看前几页，避免大文件拖慢）
PDF_TEXT_CHECK_PAGES = 3

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_LABEL = {STATUS_OK: "成功", STATUS_FAILED: "失败", STATUS_SKIPPED: "跳过"}

SCANNED_PDF_WARNING = (
    "警告：疑似扫描版 PDF（前几页无文字层），转出的文本格式可能内容缺失；"
    "建议保持 PDF 并使用 k2pdfopt 重排（后续版本将内置）。"
)


class EngineNotFoundError(Exception):
    """找不到 Calibre 转换引擎（ebook-convert）。"""


def find_engine():
    """定位 ebook-convert：先查 PATH，再查 Calibre 常见安装位置。返回 Path 或 None。"""
    found = shutil.which("ebook-convert")
    if found:
        return Path(found)
    for path in CALIBRE_FALLBACK_PATHS:
        if path.is_file():
            return path
    return None


def scan_folder(folder):
    """扫描文件夹第一层，返回其中可转换的文件列表（按文件名排序）。

    跳过子目录、以 . 或 ~$ 开头的隐藏/临时文件。
    """
    folder = Path(folder)
    results = []
    for entry in sorted(folder.iterdir()):
        if not entry.is_file():
            continue
        if entry.name.startswith(".") or entry.name.startswith("~$"):
            continue
        if entry.suffix.lower() in INPUT_EXTENSIONS:
            results.append(entry)
    return results


def build_command(engine, src, dst):
    """构造 ebook-convert 命令行。"""
    return [str(engine), str(src), str(dst)]


def pdf_has_text_layer(pdf_path, pages_to_check=PDF_TEXT_CHECK_PAGES):
    """检查 PDF 前 pages_to_check 页是否有文字层。

    返回 True / False；依赖缺失或文件打不开时返回 None（无法判断，不告警）。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return None
    try:
        if doc.page_count == 0:
            return None
        for i in range(min(doc.page_count, pages_to_check)):
            if doc[i].get_text().strip():
                return True
        return False
    finally:
        doc.close()


def _fail(dst, message):
    """记一次失败：清理残缺输出文件，避免下次被'输出已存在'误跳过。"""
    Path(dst).unlink(missing_ok=True)
    return STATUS_FAILED, message


# 引擎 stderr 进度输出形如 "34%"（用 \r 覆盖刷新）
_PROGRESS_PATTERN = re.compile(r"(\d{1,3})\s*%")


def _drain(stream, chunks, on_progress):
    """逐行读取引擎输出：收集 stderr 内容并回调解析出的进度百分比（只增不减）。"""
    highest = 0
    try:
        for line in stream:
            chunks.append(line)
            if on_progress is not None:
                for match in _PROGRESS_PATTERN.finditer(line):
                    pct = int(match.group(1))
                    if 0 <= pct <= 100 and pct > highest:
                        highest = pct
                        on_progress(pct)
    except (OSError, ValueError):
        pass  # 管道随子进程关闭产生的读写异常不影响结果判定


def convert_file(engine, src, dst, on_progress=None):
    """转换单个文件，返回 (status, message)。

    status 取值：ok / failed / skipped。任何情况下都不改动源文件；
    失败（含超时、Ctrl+C 中断）时清理已产生的残缺输出。
    on_progress(pct) 可选：转换过程中收到引擎 stderr 解析出的百分比（0~100）。
    """
    src, dst = Path(src), Path(dst)
    if dst.exists():
        return STATUS_SKIPPED, "输出已存在"

    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = None
    stderr = ""
    try:
        proc = subprocess.Popen(
            build_command(engine, src, dst),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if on_progress is None:
            try:
                _, stderr = proc.communicate(timeout=CONVERT_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return _fail(dst, "转换超时")
        else:
            # ebook-convert 把进度与日志输出到 stdout（如 "67% 正在运行 … 插件"），
            # 错误信息走 stderr；两路都排空防管道写满阻塞
            chunks = []
            err_chunks = []
            readers = [
                threading.Thread(target=_drain, args=(proc.stdout, chunks, on_progress), daemon=True),
                threading.Thread(target=_drain, args=(proc.stderr, err_chunks, None), daemon=True),
            ]
            for reader in readers:
                reader.start()
            try:
                proc.wait(timeout=CONVERT_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return _fail(dst, "转换超时")
            for reader in readers:
                reader.join(timeout=5)
            stderr = "".join(err_chunks)
    except KeyboardInterrupt:
        if proc is not None:
            proc.kill()
            try:
                proc.communicate(timeout=10)
            except BaseException:
                pass  # 清理阶段的二次 Ctrl+C 等异常不能阻断输出文件清理
        dst.unlink(missing_ok=True)
        raise
    except OSError as exc:
        return STATUS_FAILED, f"无法启动转换引擎: {exc}"

    if proc.returncode != 0:
        lines = (stderr or "").strip().splitlines()
        detail = lines[-1] if lines else f"退出码 {proc.returncode}"
        return _fail(dst, detail)

    if not dst.exists():
        return STATUS_FAILED, "转换引擎未产生输出文件"
    size = dst.stat().st_size
    if size < MIN_OUTPUT_BYTES:
        return _fail(dst, f"输出仅 {size} 字节，疑似转换失败")
    return STATUS_OK, f"{dst.name}（{size // 1024} KB）"


def run_conversion(src_folder, target_format, out_folder, engine=None,
                   on_start=None, on_result=None):
    """批量转换 src_folder 下所有可转换文件，返回 [(源文件, status, message)]。

    on_start(files) 在转换开始前调用；on_result(src, status, message)
    每转完一个文件调用一次，用于实时输出进度。
    """
    if engine is None:
        engine = find_engine()
        if engine is None:
            raise EngineNotFoundError("未找到 ebook-convert，请先安装 Calibre")

    out_folder = Path(out_folder)
    files = scan_folder(src_folder)
    if on_start is not None:
        on_start(files)

    results = []
    seen_dst = {}  # dst 路径 -> 先占用它的源文件名
    for src in files:
        dst = out_folder / (src.stem + "." + target_format)
        if dst in seen_dst:
            status, message = STATUS_SKIPPED, f"输出与 {seen_dst[dst]} 重名"
        else:
            warning = ""
            if src.suffix.lower() == ".pdf" and target_format != "pdf":
                if pdf_has_text_layer(src) is False:
                    warning = SCANNED_PDF_WARNING
            status, message = convert_file(engine, src, dst)
            if warning and status == STATUS_OK:
                message = f"{message}；{warning}"
            seen_dst[dst] = src.name
        results.append((src, status, message))
        if on_result is not None:
            on_result(src, status, message)
    return results


def prompt_folder(title):
    """交互式获取一个已存在的文件夹路径。"""
    while True:
        raw = input(title + "：").strip().strip('"')
        path = Path(raw) if raw else None
        if path is not None and path.is_dir():
            return path
        print("  路径不存在或不是文件夹，请重新输入")


def prompt_format():
    """交互式选择目标格式。"""
    print("可转换成的格式：")
    for i, fmt in enumerate(OUTPUT_FORMATS, 1):
        print(f"  [{i:>2}] {fmt}")
    while True:
        raw = input("请输入编号或格式名：").strip().lower()
        if raw.isdigit() and 1 <= int(raw) <= len(OUTPUT_FORMATS):
            return OUTPUT_FORMATS[int(raw) - 1]
        if raw in OUTPUT_FORMATS:
            return raw
        print("  无效选择，请重新输入")


def build_parser():
    parser = argparse.ArgumentParser(
        description="电子书格式转换器：批量把文件夹里的电子书转换成指定格式（引擎：Calibre）"
    )
    parser.add_argument("folder", nargs="?", help="要转换的文件夹路径（不填则交互输入）")
    parser.add_argument("-f", "--format", choices=OUTPUT_FORMATS, help="目标格式（不填则交互选择）")
    parser.add_argument("-o", "--output", help="输出目录（默认：<源文件夹>\\converted）")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    print("=== 电子书格式转换器 ===")

    engine = find_engine()
    if engine is None:
        print("未找到 Calibre 转换引擎（ebook-convert）。")
        print("请先安装：winget install calibre.calibre，或到 https://calibre-ebook.com/download 下载。")
        return 2

    src = Path(args.folder) if args.folder else prompt_folder("请输入要转换的文件夹路径")
    target_format = args.format or prompt_format()
    out = Path(args.output) if args.output else src / "converted"

    print()
    print(f"转换引擎: {engine}")
    print(f"源文件夹: {src}")
    print(f"目标格式: {target_format}")
    print(f"输出目录: {out}")
    print()

    def print_start(files):
        if not files:
            print("该文件夹中没有找到可转换的文件。")
            print("支持的输入格式：" + " ".join(sorted(ext.lstrip('.') for ext in INPUT_EXTENSIONS)))

    def print_result(src_file, status, message):
        print(f"[{STATUS_LABEL[status]}] {src_file.name} -> {message}")

    try:
        results = run_conversion(src, target_format, out, engine=engine,
                                 on_start=print_start, on_result=print_result)
    except KeyboardInterrupt:
        print()
        print("已中断：残缺的输出文件已清理，已完成的文件保留。")
        return 130

    if not results:
        return 0

    failed = [r for r in results if r[1] == STATUS_FAILED]
    print()
    print(f"完成：成功 {len(results) - len(failed)}，"
          f"跳过 {sum(1 for r in results if r[1] == STATUS_SKIPPED)}，失败 {len(failed)}")
    if failed:
        print("失败的文件已保留源文件并清理残缺输出，可修复后重试。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
