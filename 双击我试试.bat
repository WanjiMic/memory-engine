@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem —— 找一个能用的 Python（3.9+）
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto nopython

if not exist "demo\data\memory.db" goto build
goto loop

:build
echo.
echo 第一次运行，正在给自带的 demo 建索引，十几秒就好……
%PY% -m engine.import_memories --config demo\config.json
if errorlevel 1 goto buildfail

:loop
echo.
set "kw="
set /p "kw=输入一个词看看能捞回什么（直接回车就退出）："
if "!kw!"=="" goto end
%PY% -m engine.search --config demo\config.json "!kw!"
goto loop

:end
echo.
echo 好了，就这些。想换成你自己的笔记，看 README 里「装上，用它读你自己的文件」那一节。
pause
exit /b 0

:nopython
echo.
echo 没找到能用的 Python（需要 3.9 或更新）。
echo 去 https://www.python.org/downloads/ 下 Windows 版，装的时候记得勾上：
echo     [x] Add python.exe to PATH
echo 装完再双击我。
pause
exit /b 1

:buildfail
echo.
echo 建索引失败了。把上面那段报错原样贴给作者就行。
pause
exit /b 1
