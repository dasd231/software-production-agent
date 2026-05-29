@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo ???????http://127.0.0.1:7860
echo ???????showcase_admin / 12345678
start "" http://127.0.0.1:7860
python -m agent.ui.app --host 127.0.0.1 --port 7860 --runs-root product_runs
pause
