@echo off
REM DeepSeek 本地部署启动脚本
REM 使用 vLLM 部署 DeepSeek 模型

echo 🚀 启动 DeepSeek 本地服务...
echo.

cd /d "%~dp0.."

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 Python，请确保已安装 Python 3.8+
    pause
    exit /b 1
)

REM 启动DeepSeek服务
python scripts\deploy_deepseek.py %*

if errorlevel 1 (
    echo.
    echo ❌ 部署失败
    echo 请检查错误信息并重试
    pause
    exit /b 1
)

echo.
echo ✅ DeepSeek 服务已停止
pause