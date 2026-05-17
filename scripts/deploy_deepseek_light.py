#!/usr/bin/env python3
"""
DeepSeek 轻量级部署脚本
适用于资源有限的环境，使用较小的模型或CPU推理
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

def deploy_lightweight_deepseek():
    """部署轻量级DeepSeek模型"""
    print("🤖 DeepSeek 轻量级部署工具")
    print("=" * 50)

    # 检查是否有GPU
    try:
        result = subprocess.run([sys.executable, "-c", "import torch; print(torch.cuda.is_available())"],
                              capture_output=True, text=True, timeout=10)
        has_cuda = "True" in result.stdout.strip()
    except:
        has_cuda = False

    print(f"🔍 检测到 CUDA: {'是' if has_cuda else '否'}")

    if has_cuda:
        print("💡 推荐使用 GPU 部署 DeepSeek-V2.5")
        model = "deepseek-ai/DeepSeek-V2.5"
        gpu_memory = 0.8
    else:
        print("💡 使用 CPU 模式，推荐较小模型")
        print("⚠️  CPU 推理速度会很慢，仅用于测试")
        model = "deepseek-ai/DeepSeek-V2.5"  # 即使是CPU也尝试V2.5，但可能失败
        gpu_memory = 0.0

    # 安装依赖
    print("\n📦 安装依赖...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "vllm", "huggingface-hub"])
    except subprocess.CalledProcessError:
        print("❌ 依赖安装失败")
        return False

    # 启动服务
    print(f"\n🚀 启动服务 (模型: {model})...")

    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", model,
        "--host", "127.0.0.1",
        "--port", "8000",
        "--api-key", "dummy",
        "--max-model-len", "4096",  # 减少上下文长度以适应内存
    ]

    if has_cuda:
        cmd.extend([
            "--gpu-memory-utilization", str(gpu_memory),
            "--tensor-parallel-size", "1",
        ])
    else:
        cmd.extend([
            "--device", "cpu",  # 强制CPU模式
            "--dtype", "float16",  # 使用半精度减少内存
        ])

    print(f"执行命令: {' '.join(cmd[:5])}...")  # 只显示前5个参数

    try:
        # 启动进程
        process = subprocess.Popen(cmd)

        # 等待服务启动
        import time
        import requests

        print("等待服务启动...")
        for i in range(120):  # 最多等待2分钟
            try:
                response = requests.get("http://127.0.0.1:8000/health", timeout=5)
                if response.status_code == 200:
                    print("✅ DeepSeek 服务启动成功！")
                    print("   API 地址: http://127.0.0.1:8000/v1")
                    print(f"   模型: {model}")
                    print(f"   模式: {'GPU' if has_cuda else 'CPU'}")
                    print(f"   进程ID: {process.pid}")

                    # 更新环境变量
                    update_env_file()
                    return process
            except requests.exceptions.RequestException:
                pass

            if i % 10 == 0:
                print(f"等待服务启动... ({i+1}/120)")
            time.sleep(1)

        print("❌ 服务启动超时")
        process.terminate()
        return None

    except Exception as e:
        print(f"❌ 服务启动失败: {e}")
        return None

def update_env_file():
    """更新环境变量"""
    env_file = Path(".env.local")
    print(f"\n📝 更新环境变量文件: {env_file}")

    env_content = ""
    if env_file.exists():
        env_content = env_file.read_text(encoding="utf-8")

    updates = {
        "MAIN_DEEPSEEK_BASE_URL": "http://127.0.0.1:8000/v1",
        "MAIN_DEEPSEEK_MODEL": "deepseek-ai/DeepSeek-V2.5",
        "MAIN_DEEPSEEK_API_KEY": "dummy"
    }

    lines = env_content.splitlines() if env_content else []
    existing_vars = {line.split('=')[0] for line in lines if '=' in line}

    for var, value in updates.items():
        if var not in existing_vars:
            lines.append(f"{var}={value}")
        else:
            for i, line in enumerate(lines):
                if line.startswith(f"{var}="):
                    lines[i] = f"{var}={value}"
                    break

    env_file.write_text('\n'.join(lines) + '\n', encoding="utf-8")
    print("✅ 环境变量已更新")

def test_service():
    """测试服务"""
    print("\n🧪 测试服务...")

    try:
        import requests

        # 测试健康检查
        response = requests.get("http://127.0.0.1:8000/health", timeout=10)
        if response.status_code != 200:
            print("❌ 健康检查失败")
            return False

        # 测试模型列表
        response = requests.get("http://127.0.0.1:8000/v1/models", timeout=10)
        if response.status_code != 200:
            print("❌ 模型列表获取失败")
            return False

        print("✅ 服务测试通过")
        return True

    except Exception as e:
        print(f"❌ 服务测试失败: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="DeepSeek 轻量级部署")
    parser.add_argument("--cpu-only", action="store_true", help="强制使用CPU模式")
    args = parser.parse_args()

    # 如果指定CPU模式，修改环境变量
    if args.cpu_only:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    process = deploy_lightweight_deepseek()

    if process:
        if test_service():
            print("\n🎉 DeepSeek 部署完成！")
            print("现在可以在软件生产Agent中使用本地DeepSeek模型了")
            print("按 Ctrl+C 停止服务")

            try:
                process.wait()
            except KeyboardInterrupt:
                print("\n🛑 正在停止服务...")
                process.terminate()
                process.wait()
                print("✅ 服务已停止")
        else:
            print("⚠️  服务部署完成但测试失败，请检查配置")
    else:
        print("❌ 部署失败")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())