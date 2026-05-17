#!/usr/bin/env python3
"""Lightweight DeepSeek OpenAI-compatible server using Transformers.

This is intended for Windows/dev machines where vLLM is unavailable or the GPU
cannot host the larger DeepSeek models. It exposes the subset used by this
project: /health, /v1/models and /v1/chat/completions.
"""

from __future__ import annotations

import argparse
import os
import time
import uuid
from pathlib import Path
from typing import Any

# Avoid importing optional broken TensorFlow/Flax installations when
# Transformers lazily resolves PyTorch model classes.
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer


DEFAULT_MODEL = "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B"


class ChatMessage(BaseModel):
    role: str
    content: str | None = ""


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float = 0.2
    max_tokens: int = Field(default=512, ge=1, le=4096)
    top_p: float = Field(default=0.95, gt=0.0, le=1.0)


def _device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def _dtype(device: str):
    return torch.float16 if device == "cuda" else torch.float32


def _update_env_file(env_file: Path, *, base_url: str, model: str) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    updates = {
        "MAIN_DEEPSEEK_BASE_URL": base_url,
        "MAIN_DEEPSEEK_MODEL": model,
        "MAIN_DEEPSEEK_API_KEY": "dummy",
    }
    existing = {line.split("=", 1)[0] for line in lines if "=" in line and not line.strip().startswith("#")}
    for key, value in updates.items():
        if key not in existing:
            lines.append(f"{key}={value}")
            continue
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                break
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_prompt(tokenizer: Any, messages: list[ChatMessage]) -> str:
    payload = [{"role": msg.role, "content": msg.content or ""} for msg in messages]
    if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template:
        return tokenizer.apply_chat_template(payload, tokenize=False, add_generation_prompt=True)
    parts: list[str] = []
    for msg in payload:
        parts.append(f"{msg['role']}: {msg['content']}")
    parts.append("assistant:")
    return "\n".join(parts)


def create_app(model_name: str, *, max_input_tokens: int, max_new_tokens_cap: int) -> FastAPI:
    app = FastAPI(title="Local DeepSeek Transformers Server")
    device = _device()
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=_dtype(device),
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    model.to(device)
    model.eval()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "model": model_name, "device": device}

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": model_name, "object": "model", "created": 0, "owned_by": "local"}],
        }

    @app.post("/v1/chat/completions")
    def chat_completions(req: ChatCompletionRequest) -> dict[str, Any]:
        if not req.messages:
            raise HTTPException(status_code=400, detail="messages must not be empty")
        prompt = _format_prompt(tokenizer, req.messages)
        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=max_input_tokens,
        ).to(device)
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=min(int(req.max_tokens), max(int(max_new_tokens_cap), 1)),
                do_sample=float(req.temperature) > 0,
                temperature=max(float(req.temperature), 1e-5),
                top_p=float(req.top_p),
                pad_token_id=tokenizer.eos_token_id,
            )
        generated = output[0][inputs["input_ids"].shape[-1] :]
        text = tokenizer.decode(generated, skip_special_tokens=True).strip()
        return {
            "id": "chatcmpl-" + uuid.uuid4().hex,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": int(inputs["input_ids"].shape[-1]),
                "completion_tokens": int(generated.shape[-1]),
                "total_tokens": int(inputs["input_ids"].shape[-1] + generated.shape[-1]),
            },
        }

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve lightweight DeepSeek via Transformers")
    parser.add_argument("--model", default=os.environ.get("MAIN_DEEPSEEK_MODEL", DEFAULT_MODEL))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--max-input-tokens", type=int, default=2048)
    parser.add_argument("--max-new-tokens-cap", type=int, default=128)
    parser.add_argument("--env-file", type=Path, default=Path(".env.local"))
    parser.add_argument("--no-env-update", action="store_true")
    args = parser.parse_args()

    if not args.no_env_update:
        _update_env_file(
            args.env_file,
            base_url=f"http://{args.host}:{args.port}/v1",
            model=args.model,
        )

    app = create_app(
        args.model,
        max_input_tokens=max(int(args.max_input_tokens), 256),
        max_new_tokens_cap=max(int(args.max_new_tokens_cap), 1),
    )
    uvicorn.run(app, host=args.host, port=int(args.port), log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
