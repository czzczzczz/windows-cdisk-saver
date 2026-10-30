@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "APP=%~dp0main.py"

if not exist "%APP%" (
    echo.
    echo  [错误] 找不到 main.py，请确认本文件与 main.py 在同一目录。
    echo.
    pause
    exit /b 1
)

rem ============================================================
rem  默认以管理员身份启动
rem  处理 ProgramData / Windows 下的目录需要管理员权限，
rem  目录联接本身不需要。想用普通权限调试：启动.bat /noadmin
rem ============================================================
if /i "%~1"=="/noadmin" goto findpy

net session >nul 2>&1
if errorlevel 1 (
    echo 正在申请管理员权限 ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:findpy
set "FOUND="

rem ---- 1. 固定候选路径 ----
for %%P in (
  "%~dp0.venv\Scripts\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
  "C:\Python313\python.exe"
  "C:\Python312\python.exe"
  "C:\Python311\python.exe"
  "C:\Python310\python.exe"
) do (
    if not defined FOUND if exist %%P (
        %%P -c "import tkinter" >nul 2>nul
        if !errorlevel!==0 set "FOUND=%%~P"
    )
)

rem ---- 2. PATH 中的 python（同样要过 tkinter 检测）----
if not defined FOUND (
    for /f "delims=" %%I in ('where python.exe 2^>nul') do (
        if not defined FOUND (
            %%I -c "import tkinter" >nul 2>nul
            if !errorlevel!==0 set "FOUND=%%I"
        )
    )
)

if not defined FOUND (
    echo.
    echo  [错误] 没有找到可用的 Python。
    echo.
    echo  需要 Python 3.9 及以上，且必须带 tkinter 组件。
    echo  注意：精简版 / 内嵌版 / 部分绿色版 Python 不带 tkinter，无法运行。
    echo  官方安装包默认包含，下载：https://www.python.org/downloads/
    echo.
    echo  可以双击「诊断.bat」查看每个 Python 的检测结果。
    echo.
    pause
    exit /b 1
)

set "PYW=!FOUND:python.exe=pythonw.exe!"
if not exist "!PYW!" set "PYW=!FOUND!"

start "" "!PYW!" "%APP%"
exit /b 0
