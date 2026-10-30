# -*- coding: utf-8 -*-
"""PyInstaller 打包入口：`python run_webapp.py` 等价于 `python -m webapp.app`。

打包命令见 build_exe.bat；Calibre 本体不打包，运行时自动探测并引导安装。
"""

from webapp.app import main

if __name__ == "__main__":
    raise SystemExit(main())
