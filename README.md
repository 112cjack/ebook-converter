# 电子书格式转换器

把一个文件夹里的电子书批量转换成你选择的目标格式。转换引擎使用 [Calibre](https://calibre-ebook.com/) 自带的 `ebook-convert`，纯本地运行，不上传任何文件。

## 环境要求

| 依赖 | 必需 | 说明 |
|------|------|------|
| Python 3.10+ | 是 | 运行时依赖见 `requirements.txt` |
| [Calibre](https://calibre-ebook.com/download) | 是 | 转换引擎，脚本会自动探测安装位置 |

```
winget install calibre.calibre
pip install -r requirements.txt
```

## 使用方法

```
python ebook_converter.py                          # 交互式：输入文件夹、选择格式
python ebook_converter.py D:\Books -f mobi        # 直接指定文件夹和目标格式
python ebook_converter.py D:\Books -f epub -o D:\Out
```

流程：选择源文件夹 → 选择目标格式（epub / mobi / azw3 / pdf / txt / docx / rtf / fb2 / odt / htmlz）→ 开始批量转换，**每转完一个文件立即输出结果**，最后汇总成功 / 跳过 / 失败数量。

## 支持的输入格式

azw、azw3、azw4、cbz、cbr、cbc、chm、djvu、docx、epub、fb2、fbz、html、htmlz、lit、lrf、mobi、odt、pdb、pdf、pml、prc、rb、rtf、snb、tcr、txt、txtz（以 Calibre 官方支持列表为准）。

## 行为约定

- **源文件永不删除/修改**：输出统一写到输出目录，失败时保留源文件，可修复后重试
- **残缺输出自动清理**：转换失败、超时或 Ctrl+C 中断时，残缺的输出文件会被删除，避免下次运行被"输出已存在"误跳过
- 输出文件已存在时**跳过**，不覆盖；同批文件转换目标重名时**明确提示**与哪个文件冲突
- **扫描版 PDF 检测**：PDF 转"文本类"格式前会检查文字层，无文字层（扫描版）时给出警告——内容是图片，转文本格式会缺失，建议保持 PDF 并用 k2pdfopt 重排
- 转换结果校验：输出文件缺失或小于 1KB 视为失败（沿用 kindle-auto-convert 的校验规则）
- 单个文件转换超时上限 30 分钟

## 开发

```
pip install -r requirements-dev.txt
python -m pytest tests -v
```

测试共 31 个，包含调用真实 Calibre 的集成测试（本机未安装 Calibre 时自动跳过）和用 PyMuPDF 生成真实扫描版/文字版 PDF 的检测测试。

## 许可证

[MIT License](LICENSE)

## 路线图

- [ ] 扫描版 PDF：k2pdfopt 重排 + 可选 OCR（迁移自 kindle-auto-convert）
- [ ] 递归扫描子文件夹、转换日志文件
- [ ] 一本书同时导出多种格式
- [ ] 图形界面 / 打包 exe（让非技术用户开箱即用）
- [ ] 旧项目 USB 设备监听 / Kindle 自动转换功能的迁移
