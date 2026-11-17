@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

title J.T.C.A A股量化分析工具

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [J.T.C.A] 未找到虚拟环境 .venv
  echo.
  echo 请先在本目录执行：
  echo   python -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
  echo.
  echo 然后在 .env 中填写 DEEPSEEK_API_KEY，再双击本文件。
  echo.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" run.py

echo.
echo [J.T.C.A] 服务已停止。
pause
endlocal
