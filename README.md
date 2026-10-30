# 电子书格式转换器

把一个文件夹里的电子书批量转换成你选择的目标格式。转换引擎使用 [Calibre](https://calibre-ebook.com/) 自带的 `ebook-convert`，纯本地运行。

> 当前为 **MVP 版本**：命令行交互式工具，扫描文件夹第一层，输出到 `<源文件夹>\converted`。旧项目 kindle-auto-convert 的扫描版 PDF 重排（k2pdfopt）、OCR、USB 设备监听等功能将在后续迭代中迁移。

## 环境要求

| 依赖 | 必需 | 说明 |
|------|------|------|
| Python 3.10+ | 是 | 无第三方依赖 |
| [Calibre](https://calibre-ebook.com/download) | 是 | 转换引擎，脚本会自动探测安装位置 |

```
winget install calibre.calibre
```

## 使用方法

```
python ebook_converter.py                          # 交互式：输入文件夹、选择格式
python ebook_converter.py D:\Books -f mobi        # 直接指定文件夹和目标格式
python ebook_converter.py D:\Books -f epub -o D:\Out
```

流程：选择源文件夹 → 选择目标格式（epub / mobi / azw3 / pdf / txt / docx / rtf / fb2 / odt / htmlz）→ 开始批量转换，逐个显示成功 / 失败 / 跳过，最后汇总。

## 支持的输入格式

azw、azw3、azw4、cbz、cbr、cbc、chm、djvu、docx、epub、fb2、fbz、html、htmlz、lit、lrf、mobi、odt、pdb、pdf、pml、prc、rb、rtf、snb、tcr、txt、txtz（以 Calibre 官方支持列表为准）。

## 行为约定

- **源文件永不删除/修改**：输出统一写到输出目录，失败时保留源文件，可修复后重试
- 输出文件已存在时**跳过**，不覆盖
- 转换结果校验：输出文件缺失或小于 1KB 视为失败（沿用 kindle-auto-convert 的校验规则）
- 单个文件转换超时上限 30 分钟

## 开发

```
pip install -r requirements-dev.txt
python -m pytest tests -v
```

测试包含调用真实 Calibre 的集成测试（本机未安装 Calibre 时自动跳过）。

## 后续迭代计划

- 扫描版 PDF：k2pdfopt 重排 + 可选 OCR（迁移自 kindle-auto-convert）
- 递归扫描子文件夹、转换日志文件
- 旧项目 USB 设备监听 / Kindle 自动转换功能的迁移
