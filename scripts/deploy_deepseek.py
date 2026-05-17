#!/usr/bin/env python3
"""
DeepSeek 本地部署脚本
使用 vLLM 部署 DeepSeek 模型作为 OpenAI-compatible API 服务

支持的模型：
- deepseek-ai/DeepSeek-V3 (推荐)
- deepseek-ai/DeepSeek-V2.5
- deepseek-ai/DeepSeek-Coder-V2

环境要求：
- Python 3.8+
- CUDA 11.8+ (推荐)
- 至少 16GB VRAM (V3模型)
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# 默认配置
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_WORKERS = 1

# 模型配置
MODEL_CONFIGS = {
    "deepseek-ai/DeepSeek-V3": {
        "size": "671B",
        "vram": "128GB+",
        "description": "DeepSeek-V3 主力模型，性能最强"
    },
    "deepseek-ai/DeepSeek-V2.5": {
        "size": "236B",
        "vram": "48GB+",
        "description": "DeepSeek-V2.5 中等规模模型"
    },
    "deepseek-ai/DeepSeek-Coder-V2": {
        "size": "236B",
        "vram": "48GB+",
        "description": "DeepSeek-Coder-V2 代码专用模型"
    }
}

def check_requirements():
    """检查系统要求"""
    print("🔍 检查系统要求...")

    # 检查Python版本
    if sys.version_info < (3, 8):
        print("❌ 需要 Python 3.8+")
        return False

    # 检查CUDA
    try:
        result = subprocess.run([sys.executable, "-c", "import torch; print(torch.cuda.is_available())"],
                              capture_output=True, text=True)
        if "True" not in result.stdout:
            print("⚠️  CUDA 未检测到，将使用 CPU 模式（性能会显著下降）")
    except:
        print("⚠️  无法检测 CUDA")

    print("✅ 系统要求检查完成")
    return True

def install_vllm():
    """安装 vLLM"""
    print("📦 安装 vLLM...")

    try:
        # 首先尝试安装 vLLM
        subprocess.check_call([sys.executable, "-m", "pip", "install", "vllm"])

        # 验证安装
        result = subprocess.run([sys.executable, "-c", "import vllm; print('vLLM version:', vllm.__version__)"],
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ vLLM 安装成功: {result.stdout.strip()}")
            return True
        else:
            print("❌ vLLM 安装失败")
            return False
    except subprocess.CalledProcessError as e:
        print(f"❌ vLLM 安装失败: {e}")
        return False

def download_model(model_name: str):
    """预下载模型（可选）"""
    print(f"📥 预下载模型: {model_name}")

    try:
        # 使用 huggingface_hub 下载模型
        subprocess.check_call([
            sys.executable, "-c",
            f"from huggingface_hub import snapshot_download; snapshot_download('{model_name}')"
        ])
        print("✅ 模型下载完成")
        return True
    except:
        print("⚠️  模型预下载失败，将在启动时自动下载")
        return False

def start_vllm_server(model: str, host: str, port: int, workers: int, gpu_memory_utilization: float = 0.9):
    """启动 vLLM OpenAI API 服务器"""
    print(f"🚀 启动 DeepSeek vLLM 服务器...")
    print(f"   模型: {model}")
    print(f"   地址: http://{host}:{port}")
    print(f"   GPU内存利用率: {gpu_memory_utilization}")

    # 构建命令
    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", model,
        "--host", host,
        "--port", str(port),
        "--api-key", "dummy",  # 本地部署使用dummy key
        "--gpu-memory-utilization", str(gpu_memory_utilization),
        "--max-model-len", "32768",  # 设置最大上下文长度
        "--tensor-parallel-size", str(workers),
    ]

    # 如果是DeepSeek-Coder，添加代码相关参数
    if "coder" in model.lower():
        cmd.extend([
            "--trust-remote-code",
            "--enforce-eager"
        ])

    print(f"执行命令: {' '.join(cmd)}")
    print("服务启动中，请稍候...")

    try:
        # 启动服务
        process = subprocess.Popen(cmd)

        # 等待服务启动
        import time
        import requests

        for i in range(60):  # 最多等待60秒
            try:
                response = requests.get(f"http://{host}:{port}/health", timeout=5)
                if response.status_code == 200:
                    print("✅ DeepSeek 服务启动成功！")
                    print(f"   API 地址: http://{host}:{port}/v1")
                    print(f"   模型: {model}")
                    print(f"   进程ID: {process.pid}")
                    return process
            except:
                pass

            print(f"等待服务启动... ({i+1}/60)")
            time.sleep(1)

        print("❌ 服务启动超时")
        process.terminate()
        return None

    except Exception as e:
        print(f"❌ 服务启动失败: {e}")
        return None

def update_env_file(env_file: Path, host: str, port: int, model: str):
    """更新环境变量文件"""
    print(f"📝 更新环境变量文件: {env_file}")

    env_content = ""
    if env_file.exists():
        env_content = env_file.read_text(encoding="utf-8")

    # 需要更新的变量
    updates = {
        "MAIN_DEEPSEEK_BASE_URL": f"http://{host}:{port}/v1",
        "MAIN_DEEPSEEK_MODEL": model,
        "MAIN_DEEPSEEK_API_KEY": "dummy"
    }

    # 检查是否已存在这些变量
    lines = env_content.splitlines()
    existing_vars = {line.split('=')[0] for line in lines if '=' in line}

    # 添加或更新变量
    for var, value in updates.items():
        if var not in existing_vars:
            lines.append(f"{var}={value}")
        else:
            # 更新现有变量
            for i, line in enumerate(lines):
                if line.startswith(f"{var}="):
                    lines[i] = f"{var}={value}"
                    break

    # 写回文件
    env_file.write_text('\n'.join(lines) + '\n', encoding="utf-8")
    print("✅ 环境变量已更新")

def test_service(host: str, port: int, model: str):
    """测试服务是否正常工作"""
    print("🧪 测试服务功能...")

    try:
        import requests

        # 测试健康检查
        response = requests.get(f"http://{host}:{port}/health")
        if response.status_code != 200:
            print("❌ 健康检查失败")
            return False

        # 测试模型列表
        response = requests.get(f"http://{host}:{port}/v1/models")
        if response.status_code != 200:
            print("❌ 模型列表获取失败")
            return False

        models_data = response.json()
        available_models = [m['id'] for m in models_data.get('data', [])]

        if model not in available_models:
            print(f"❌ 模型 {model} 不在可用模型列表中")
            return False

        # 测试聊天完成
        test_payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hello, test message"}],
            "max_tokens": 50
        }

        response = requests.post(
            f"http://{host}:{port}/v1/chat/completions",
            json=test_payload,
            headers={"Authorization": "Bearer dummy"}
        )

        if response.status_code != 200:
            print(f"❌ 聊天测试失败: {response.status_code}")
            return False

        result = response.json()
        if 'choices' not in result or not result['choices']:
            print("❌ 聊天响应格式错误")
            return False

        print("✅ 服务测试通过")
        return True

    except Exception as e:
        print(f"❌ 服务测试失败: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="DeepSeek 本地部署脚本")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                       choices=list(MODEL_CONFIGS.keys()),
                       help=f"要部署的模型 (默认: {DEFAULT_MODEL})")
    parser.add_argument("--host", default=DEFAULT_HOST,
                       help=f"服务主机地址 (默认: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                       help=f"服务端口 (默认: {DEFAULT_PORT})")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                       help=f"并行worker数量 (默认: {DEFAULT_WORKERS})")
    parser.add_argument("--gpu-memory", type=float, default=0.9,
                       help="GPU内存利用率 (默认: 0.9)")
    parser.add_argument("--download-only", action="store_true",
                       help="仅下载模型，不启动服务")
    parser.add_argument("--skip-install", action="store_true",
                       help="跳过vLLM安装")
    parser.add_argument("--env-file", type=Path, default=Path(".env.local"),
                       help="环境变量文件路径")

    args = parser.parse_args()

    print("🤖 DeepSeek 本地部署工具")
    print("=" * 50)

    # 显示模型信息
    model_info = MODEL_CONFIGS.get(args.model, {})
    print(f"📋 部署配置:")
    print(f"   模型: {args.model}")
    print(f"   大小: {model_info.get('size', 'Unknown')}")
    print(f"   VRAM: {model_info.get('vram', 'Unknown')}")
    print(f"   描述: {model_info.get('description', '')}")
    print(f"   地址: http://{args.host}:{args.port}")
    print()

    # 检查要求
    if not check_requirements():
        return 1

    # 安装vLLM
    if not args.skip_install:
        if not install_vllm():
            return 1

    # 预下载模型
    if not download_model(args.model):
        print("⚠️  模型预下载失败，继续启动服务...")

    if args.download_only:
        print("✅ 模型下载完成")
        return 0

    # 启动服务
    process = start_vllm_server(
        args.model,
        args.host,
        args.port,
        args.workers,
        args.gpu_memory
    )

    if not process:
        return 1

    # 测试服务
    if not test_service(args.host, args.port, args.model):
        print("⚠️  服务测试失败，但服务可能仍在运行")
        print("请手动检查服务状态")

    # 更新环境变量
    try:
        update_env_file(args.env_file, args.host, args.port, args.model)
    except Exception as e:
        print(f"⚠️  环境变量更新失败: {e}")

    print("\n🎉 DeepSeek 部署完成！")
    print("现在你可以在软件生产Agent中使用本地DeepSeek模型了")
    print(f"进程ID: {process.pid}")
    print("按 Ctrl+C 停止服务")

    try:
        process.wait()
    except KeyboardInterrupt:
        print("\n🛑 正在停止服务...")
        process.terminate()
        process.wait()
        print("✅ 服务已停止")

    return 0

if __name__ == "__main__":
    sys.exit(main())