# -*- coding: utf-8 -*-
"""电子书格式转换器（MVP）

把一个文件夹里的电子书批量转换成用户选择的目标格式。
转换引擎使用 Calibre 自带的 ebook-convert，输入格式覆盖
epub / mobi / azw3 / pdf / docx / rtf / fb2 / cbz / chm / txt 等。

用法：
    python ebook_converter.py                      # 交互式：选文件夹、选格式
    python ebook_converter.py <文件夹> -f mobi     # 命令行直接指定
    python ebook_converter.py <文件夹> -f epub -o <输出目录>

MVP 阶段只扫描文件夹第一层，输出目录默认为 <源文件夹>\\converted。
转换失败或输出异常时保留源文件，绝不改动源文件本身。
"""

import argparse
import shutil
import subprocess
import sys
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

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_LABEL = {STATUS_OK: "成功", STATUS_FAILED: "失败", STATUS_SKIPPED: "跳过"}


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


def convert_file(engine, src, dst):
    """转换单个文件，返回 (status, message)。

    status 取值：ok / failed / skipped。任何情况下都不改动源文件。
    """
    src, dst = Path(src), Path(dst)
    if dst.exists():
        return STATUS_SKIPPED, "输出已存在"

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            build_command(engine, src, dst),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CONVERT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return STATUS_FAILED, "转换超时"
    except OSError as exc:
        return STATUS_FAILED, f"无法启动转换引擎: {exc}"

    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = lines[-1] if lines else f"退出码 {proc.returncode}"
        return STATUS_FAILED, detail

    if not dst.exists():
        return STATUS_FAILED, "转换引擎未产生输出文件"
    size = dst.stat().st_size
    if size < MIN_OUTPUT_BYTES:
        return STATUS_FAILED, f"输出仅 {size} 字节，疑似转换失败"
    return STATUS_OK, f"{dst.name}（{size // 1024} KB）"


def run_conversion(src_folder, target_format, out_folder, engine=None):
    """批量转换 src_folder 下所有可转换文件，返回 [(源文件, status, message)]。"""
    if engine is None:
        engine = find_engine()
        if engine is None:
            raise EngineNotFoundError("未找到 ebook-convert，请先安装 Calibre")

    out_folder = Path(out_folder)
    results = []
    for src in scan_folder(src_folder):
        dst = out_folder / (src.stem + "." + target_format)
        status, message = convert_file(engine, src, dst)
        results.append((src, status, message))
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
        description="电子书格式转换器 MVP：批量把文件夹里的电子书转换成指定格式（引擎：Calibre）"
    )
    parser.add_argument("folder", nargs="?", help="要转换的文件夹路径（不填则交互输入）")
    parser.add_argument("-f", "--format", choices=OUTPUT_FORMATS, help="目标格式（不填则交互选择）")
    parser.add_argument("-o", "--output", help="输出目录（默认：<源文件夹>\\converted）")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    print("=== 电子书格式转换器 MVP ===")

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

    results = run_conversion(src, target_format, out, engine=engine)

    if not results:
        print("该文件夹中没有找到可转换的文件。")
        print("支持的输入格式：" + " ".join(sorted(ext.lstrip('.') for ext in INPUT_EXTENSIONS)))
        return 0

    for src_file, status, message in results:
        print(f"[{STATUS_LABEL[status]}] {src_file.name} -> {message}")

    failed = [r for r in results if r[1] == STATUS_FAILED]
    print()
    print(f"完成：成功 {len(results) - len(failed)}，"
          f"跳过 {sum(1 for r in results if r[1] == STATUS_SKIPPED)}，失败 {len(failed)}")
    if failed:
        print("失败的文件已保留源文件，可修复后重试。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
