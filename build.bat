@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   C 盘空间管家 - 打包 exe
echo ============================================
echo.

if not exist "main.py" (
    echo [错误] 当前目录没有 main.py
    pause
    exit /b 1
)

set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "!PY!" (
    echo [1/3] 创建虚拟环境 ...
    where python >nul 2>nul
    if errorlevel 1 (
        echo [错误] 未找到 python，无法创建虚拟环境。
        echo 请安装 Python 3.9+ 并勾选 Add Python to PATH。
        pause
        exit /b 1
    )
    python -m venv .venv
    if errorlevel 1 goto err
)

echo [2/3] 检查打包依赖 ...
"!PY!" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo       正在安装 pyinstaller / pillow（走清华镜像）...
    "!PY!" -m pip install --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple pyinstaller pillow
    if errorlevel 1 goto err
)

echo [3/3] 开始打包（内嵌管理员清单，双击即申请提权）...
"!PY!" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
    --uac-admin ^
    --name "C盘空间管家" ^
    --icon "assets\app.ico" ^
    --add-data "assets\app.ico;assets" ^
    --add-data "README.md;." ^
    main.py
if errorlevel 1 goto err

echo.
echo ============================================
echo  打包完成
echo  %~dp0dist\C盘空间管家.exe
echo ============================================
pause
exit /b 0

:err
echo.
echo [失败] 请查看上面的错误信息。
pause
exit /b 1
