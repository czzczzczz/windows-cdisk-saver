@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "APP=%~dp0main.py"

echo ============================================
echo   C 盘空间管家 - 环境诊断
echo ============================================
echo.

echo [1] 工作目录
echo     %~dp0
echo.

echo [2] main.py
if exist "%APP%" (echo     存在) else (echo     缺失 - 本文件必须与 main.py 放在同一目录)
echo.

echo [3] 逐个检测 Python 与 tkinter
for %%P in (
  "%~dp0.venv\Scripts\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
) do (
    if exist %%P (
        set "VER=?"
        for /f "tokens=2" %%V in ('%%P -V 2^>^&1') do set "VER=%%V"
        %%P -c "import tkinter" >nul 2>nul
        if !errorlevel!==0 (
            echo     [可用]   Python !VER!   %%P
        ) else (
            echo     [缺tk]   Python !VER!   %%P
        )
    )
)

echo.
echo [4] PATH 中的 python
for /f "delims=" %%I in ('where python.exe 2^>nul') do (
    set "VER=?"
    for /f "tokens=2" %%V in ('%%I -V 2^>^&1') do set "VER=%%V"
    %%I -c "import tkinter" >nul 2>nul
    if !errorlevel!==0 (echo     [可用]   Python !VER!   %%I) else (echo     [缺tk]   Python !VER!   %%I)
)
echo.

echo [5] 系统信息
for /f "delims=" %%V in ('ver') do echo     %%V
echo     USERPROFILE=%USERPROFILE%
echo.

echo [6] 以控制台模式启动（异常会打印在这里）
echo.
set "PY="
for %%P in (
  "%~dp0.venv\Scripts\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
) do (
    if not defined PY if exist %%P (
        %%P -c "import tkinter" >nul 2>nul
        if !errorlevel!==0 set "PY=%%~P"
    )
)

if not defined PY (
    echo  没有可用解释器，跳过启动。
    goto end
)

echo  使用：!PY!
echo --------------------------------------------
"!PY!" "%APP%"
set "RC=!errorlevel!"
echo --------------------------------------------
echo  程序已退出，退出码 !RC!

:end
echo.
pause
