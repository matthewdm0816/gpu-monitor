@echo off
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo "uv" is not installed. Installing uv via pip...
    pip install uv
)
if not exist .venv (
    echo Creating virtual environment with uv...
    uv venv
)
echo Syncing dependencies...
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
echo Starting GPU Monitor...
.venv\Scripts\python.exe gpu_monitor.py %*
