@echo off
chcp 65001 >nul
rem ============================================================
rem 电子书转换器 PyInstaller 打包脚本（可选，M4）
rem 产物：dist\ebook-converter.exe（单文件，含服务层与静态资源）
rem 依赖：pip install pyinstaller
rem ============================================================
cd /d "%~dp0"

python -m PyInstaller --onefile --name "电子书转换器" ^
  --add-data "webapp\static;webapp\static" ^
  --hidden-import "webapp.tasks" ^
  --noconfirm ^
  run_webapp.py

if errorlevel 1 (
  echo 打包失败，请检查上方错误信息。
  pause
  goto :eof
)
echo 打包完成：dist\电子书转换器.exe
pause
