@echo off
setlocal
cd /d "%~dp0"
python -c "import open3sdcm, numpy" >nul 2>&1
if errorlevel 1 (
  echo Installing the Open3SDCM converter for this Python installation...
  python -m pip install --only-binary=:all: "open3sdcm==1.1.4"
  if errorlevel 1 (
    echo.
    echo Installation failed. Check Python version and internet access.
    pause
    exit /b 1
  )
)
python web\app.py
if errorlevel 1 pause
