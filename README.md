# 电子书转换器

把电子书在你常用的格式之间批量转换。转换引擎使用 [Calibre](https://calibre-ebook.com/) 自带的 `ebook-convert`，全部转换在本机完成，**文件不上传任何服务器**。

提供两种使用方式：

- **网页版（推荐，面向普通用户）**：启动后在浏览器里拖入文件、选择格式、一键转换
- **命令行版**：适合批量处理整个文件夹

## 环境要求

| 依赖 | 必需 | 说明 |
|------|------|------|
| Python 3.10+ | 是 | 运行时依赖见 `requirements.txt` |
| [Calibre](https://calibre-ebook.com/download) | 是 | 转换引擎，程序自动探测安装位置；未安装时页面提供安装引导，也可在设置中手动指定路径 |

```
winget install calibre.calibre
pip install -r requirements.txt
```

## 网页版使用

```
双击 start.bat          （或命令行运行 python -m webapp.app）
```

程序在 `http://127.0.0.1:7788` 启动本地服务（端口被占用时自动向后递增）并自动打开浏览器，核心流程三步：

1. **导入文件**——拖拽或点击选择，支持一次多个文件
2. **选择输出格式**——EPUB / PDF / TXT / MOBI 等（与命令行版同一数据源）
3. **开始转换**——列表实时显示每个文件的排队 / 转换进度 / 完成状态，完成后可一键打开输出文件夹

行为要点：

- 仅监听本机 `127.0.0.1`，不访问局域网；设置（输出目录、引擎路径、上传上限）保存在程序目录 `settings.json`
- 转换记录保留到本次运行结束，重启后清空
- 单个文件失败不影响队列中的其他文件；失败原因以通俗文案显示并保留引擎细节
- 输出文件已存在时跳过不覆盖；同批重名文件明确提示冲突来源
- 单文件转换超时上限 30 分钟；上传大小上限默认 200 MB（可在设置中调整）

## 命令行版使用

```
python ebook_converter.py                          # 交互式：输入文件夹、选择格式
python ebook_converter.py D:\Books -f mobi        # 直接指定文件夹和目标格式
python ebook_converter.py D:\Books -f epub -o D:\Out
```

流程：选择源文件夹 → 选择目标格式（epub / mobi / azw3 / pdf / txt / docx / rtf / fb2 / odt / htmlz）→ 开始批量转换，**每转完一个文件立即输出结果**，最后汇总成功 / 跳过 / 失败数量。

## 支持的输入格式

azw、azw3、azw4、cbz、cbr、cbc、chm、djvu、docx、epub、fb2、fbz、html、htmlz、lit、lrf、mobi、odt、pdb、pdf、pml、prc、rb、rtf、snb、tcr、txt、txtz（以 Calibre 官方支持列表为准）。

## 行为约定（两个版本共同遵守）

- **源文件永不删除/修改**：输出统一写到输出目录，失败时保留源文件，可修复后重试
- **残缺输出自动清理**：转换失败、超时或中断时，残缺的输出文件会被删除，避免下次被"输出已存在"误跳过
- 输出文件已存在时**跳过**，不覆盖；同批文件转换目标重名时**明确提示**与哪个文件冲突
- **扫描版 PDF 检测**：PDF 转"文本类"格式前会检查文字层，无文字层（扫描版）时给出警告——内容是图片，转文本格式会缺失，建议保持 PDF 并用 k2pdfopt 重排
- 转换结果校验：输出文件缺失或小于 1KB 视为失败（沿用 kindle-auto-convert 的校验规则）
- 带版权保护（DRM）的书籍无法转换，属于合规限制，界面明确提示且不提供绕过手段

## 打包为 exe（可选）

```
pip install pyinstaller
build_exe.bat
```

产物为单文件 `dist\ebook-converter.exe`（服务层与静态资源已打入；Calibre 本体不打包，运行时自动探测并引导安装）。双击 exe 与双击 `start.bat` 效果一致。

## 开发

```
pip install -r requirements-dev.txt
python -m pytest tests -v
```

测试包含引擎层（转换、进度解析、格式探测、失败清理）与服务层（API 白名单、任务状态流转、失败映射、设置读写）两部分，其中服务层以假引擎替换真实 ebook-convert 保证确定性；调用真实 Calibre 的集成测试在本机未安装时自动跳过。

## 设计文档与实现补记

- `docs/产品设计文档.docx`、`docs/电子书转换器技术方案.docx`：开发依据
- `docs/方案补记.md`：实现过程中对方案未覆盖决策点的就近裁决记录

## 许可证

[MIT License](LICENSE)

## 路线图

- [ ] 扫描版 PDF：k2pdfopt 重排 + 可选 OCR（迁移自 kindle-auto-convert）
- [ ] 递归扫描子文件夹、转换日志文件
- [ ] 一本书同时导出多种格式
- [ ] 旧项目 USB 设备监听 / Kindle 自动转换功能的迁移
