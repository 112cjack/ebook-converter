@echo off
chcp 65001 >nul
rem ============================================================
rem 电子书转换器启动脚本（M4）
rem 双击运行：启动本地 Web 服务并自动打开浏览器；关闭本窗口即退出。
rem ============================================================
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python -m webapp.app
    if errorlevel 1 pause
    goto :eof
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m webapp.app
    if errorlevel 1 pause
    goto :eof
)

echo 未找到 Python，请先安装 Python 3.10 或更高版本：
echo   https://www.python.org/downloads/
echo   安装时请勾选 "Add python.exe to PATH"
pause
