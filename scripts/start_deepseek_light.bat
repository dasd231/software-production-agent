@echo off
REM DeepSeek 快速启动脚本 (轻量级版本)
REM 自动检测硬件并选择合适的部署方式

echo 🚀 启动 DeepSeek 本地服务 (轻量级)...
echo.

cd /d "%~dp0.."

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 Python，请确保已安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查CUDA
python -c "import torch; print('CUDA available:', torch.cuda.is_available())" 2>nul
if errorlevel 1 (
    echo ⚠️  PyTorch 未安装，将尝试自动安装...
    pip install torch --index-url https://download.pytorch.org/whl/cpu
)

REM 启动DeepSeek服务
python scripts\deploy_deepseek_light.py %*

if errorlevel 1 (
    echo.
    echo ❌ 部署失败
    echo 请检查错误信息并重试
    echo.
    echo 常见解决方案:
    echo 1. 确保有足够的内存 (至少16GB)
    echo 2. 如果有GPU，确保安装了CUDA
    echo 3. 检查网络连接用于下载模型
    pause
    exit /b 1
)

echo.
echo ✅ DeepSeek 服务已停止
pause