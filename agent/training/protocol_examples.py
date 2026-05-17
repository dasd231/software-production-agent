"""Curated SFT examples for strict action-protocol following.

These examples intentionally stay separate from the ordinary learning pipeline:

- they are grounded in the executable protocol, not in a repository corpus;
- they teach the model to emit one valid action JSON object and nothing else;
- they are deterministic, auditable, and safe to include in every backup-agent
  training run.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.core.protocol import validate_action_dict


_CITATIONS = [
    {"path": "agent/core/protocol.py"},
    {"path": "agent/prompts/action.txt"},
]


def _stable_id(*parts: str) -> str:
    h = hashlib.blake2b(digest_size=12)
    for part in parts:
        h.update(str(part).encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()


def _canonical_json(action: str, args: dict[str, Any]) -> str:
    validated = validate_action_dict({"type": "action", "action": action, "args": args})
    return json.dumps(validated, ensure_ascii=False, separators=(",", ":"))


_TEMPLATES: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("为了先了解当前工作区，请调用 workspace_index。只输出一行 JSON。", "workspace_index", {}),
    ("先做工作区索引，不要解释，直接返回可执行动作。", "workspace_index", {}),
    (
        "查看当前工作区下的已验收方案资源，roots=['./product_runs/solution_library']，type='solution'。只输出动作 JSON。",
        "resource_registry",
        {"type": "solution", "roots": ["./product_runs/solution_library"]},
    ),
    (
        "我要查看训练数据资源，roots=['./training_runs']，type='training_dataset'。只输出一行 JSON。",
        "resource_registry",
        {"type": "training_dataset", "roots": ["./training_runs"]},
    ),
    (
        "根据需求先做研究综合：query='怎样设计员工管理系统权限升级'，top_k=4，solution_dirs=['./product_runs/solution_library']，use_web=false。"
        " 只输出动作 JSON。",
        "research_synthesize",
        {
            "query": "怎样设计员工管理系统权限升级",
            "top_k": 4,
            "solution_dirs": ["./product_runs/solution_library"],
            "use_web": False,
        },
    ),
    (
        "执行本地研究综合，不联网：query='如何复用已有方案'，top_k=3，learning_dirs=['./learning_runs/demo']。"
        " 不要解释。",
        "research_synthesize",
        {
            "query": "如何复用已有方案",
            "top_k": 3,
            "learning_dirs": ["./learning_runs/demo"],
            "use_web": False,
        },
    ),
    (
        "准备 SFT 数据集：output_dir='./training_runs/protocol-demo'，learning_dirs=['./learning_runs/demo']，"
        "solution_dirs=['./product_runs/solution_library']，dataset_format='messages'。只返回一行 JSON。",
        "training_prepare",
        {
            "output_dir": "./training_runs/protocol-demo",
            "learning_dirs": ["./learning_runs/demo"],
            "solution_dirs": ["./product_runs/solution_library"],
            "dataset_format": "messages",
        },
    ),
    (
        "为备用模型准备训练集：output_dir='./training_runs/protocol-demo-2'，learning_dirs=['./learning_runs/demo']，"
        "eval_ratio=0.2，model_hint='deepseek-coder'。不要解释。",
        "training_prepare",
        {
            "output_dir": "./training_runs/protocol-demo-2",
            "learning_dirs": ["./learning_runs/demo"],
            "eval_ratio": 0.2,
            "model_hint": "deepseek-coder",
        },
    ),
    (
        "生成备用模型训练任务：training_dir='./training_runs/protocol-demo'，output_dir='./model_runs/protocol-demo'，"
        "base_model='deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B'，launch=false。只输出 JSON。",
        "backup_model_train",
        {
            "training_dir": "./training_runs/protocol-demo",
            "output_dir": "./model_runs/protocol-demo",
            "base_model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
            "launch": False,
        },
    ),
    (
        "我只想先生成候选任务，不要直接开训：training_dir='./training_runs/demo'，output_dir='./model_runs/demo'，"
        "adapter_name='backup-local-lora'，launch=false。返回动作 JSON。",
        "backup_model_train",
        {
            "training_dir": "./training_runs/demo",
            "output_dir": "./model_runs/demo",
            "adapter_name": "backup-local-lora",
            "launch": False,
        },
    ),
    (
        "汇总证据账本：roots=['./product_runs','./learning_runs']，output_path='evidence_ledger.json'。"
        " 只输出动作 JSON。",
        "evidence_ledger",
        {
            "roots": ["./product_runs", "./learning_runs"],
            "output_path": "evidence_ledger.json",
        },
    ),
    (
        "我要先查看运行证据，请把 roots=['./product_runs'] 写入证据账本，不需要解释。",
        "evidence_ledger",
        {"roots": ["./product_runs"]},
    ),
    (
        "评估一个长上下文 RAG 请求如何路由：goal='长上下文 RAG 任务'，require_json=true，max_output_tokens=1800。"
        " 只输出一行 JSON。",
        "model_route_plan",
        {"goal": "长上下文 RAG 任务", "require_json": True, "max_output_tokens": 1800},
    ),
    (
        "给短 API 请求规划模型池：goal='短 API 请求'，business_type='api'，max_output_tokens=256。不要解释。",
        "model_route_plan",
        {"goal": "短 API 请求", "business_type": "api", "max_output_tokens": 256},
    ),
    (
        "为模型请求申请 lease：goal='短 API 请求'，max_output_tokens=256，idempotency_key='req-001'，lease_ttl_s=20。"
        " 只输出动作 JSON。",
        "model_admission_acquire",
        {"goal": "短 API 请求", "max_output_tokens": 256, "idempotency_key": "req-001", "lease_ttl_s": 20},
    ),
    (
        "长请求还没结束，请给 lease 续租：lease_id='lease-001'，lease_ttl_s=30。只返回动作 JSON。",
        "model_admission_renew",
        {"lease_id": "lease-001", "lease_ttl_s": 30},
    ),
    (
        "把自然语言目标编译成 workflow：goal='爬取项目后生成方案并准备训练数据'，roots=['./product_runs']。"
        " 不要解释。",
        "intent_compile",
        {"goal": "爬取项目后生成方案并准备训练数据", "roots": ["./product_runs"]},
    ),
    (
        "只做 workflow 预演：spec 包含 schema='workflow.v1'、version='demo'、nodes=[]、edges=[]。"
        " 返回单行 JSON。",
        "workflow_dry_run",
        {"spec": {"schema": "workflow.v1", "version": "demo", "nodes": [], "edges": []}},
    ),
    (
        "读取 README.md，别解释，直接给动作。",
        "read_file",
        {"path": "README.md"},
    ),
    (
        "列出 Python 文件，pattern='**/*.py'。只输出 JSON。",
        "list_files",
        {"pattern": "**/*.py"},
    ),
    (
        "任务已经完成，请结束并注明 reason='done'。只输出动作 JSON。",
        "finish",
        {"reason": "done"},
    ),
    (
        "无需继续执行，安全终止本轮并写明 reason='insufficient_context'。不要解释。",
        "finish",
        {"reason": "insufficient_context"},
    ),
    # Failure-driven hard cases observed in benchmark runs. These focus on
    # confusions that ordinary generic examples do not reliably resolve.
    (
        "我不是要列目录，而是要先读取当前工作区概况。请调用 workspace_index，且只输出 action JSON。",
        "workspace_index",
        {},
    ),
    (
        "需要项目概况时不要用 list_files。现在请给出 workspace_index 动作。",
        "workspace_index",
        {},
    ),
    (
        "我要查看训练集资源；动作名必须是 resource_registry，不要把 type 直接放到最外层。"
        " roots=['./training_runs']，type='training_dataset'。",
        "resource_registry",
        {"type": "training_dataset", "roots": ["./training_runs"]},
    ),
    (
        "查询方案资源时必须保留外层 action 包装。请输出 resource_registry，"
        " type='solution'，roots=['./product_runs/solution_library']。",
        "resource_registry",
        {"type": "solution", "roots": ["./product_runs/solution_library"]},
    ),
    (
        "现在不是准备数据集，而是基于现有训练集生成备用模型训练任务。"
        " training_dir='./training_runs/v3'，output_dir='./model_runs/v3'，launch=false。",
        "backup_model_train",
        {
            "training_dir": "./training_runs/v3",
            "output_dir": "./model_runs/v3",
            "launch": False,
        },
    ),
    (
        "请区分 backup_model_train 与 training_prepare："
        " 我已经有 training_dir='./training_runs/ready'，现在要生成本地备用模型候选，"
        " output_dir='./model_runs/ready'，launch=false。",
        "backup_model_train",
        {
            "training_dir": "./training_runs/ready",
            "output_dir": "./model_runs/ready",
            "launch": False,
        },
    ),
    (
        "给长上下文请求做路由时，必须使用完整 action 包装。"
        " goal='长上下文请求'，require_json=true，max_output_tokens=2048。",
        "model_route_plan",
        {"goal": "长上下文请求", "require_json": True, "max_output_tokens": 2048},
    ),
    (
        "不要把 model_route_plan 的字段裸露在最外层。"
        " 现在请返回合法 action JSON：goal='结构化 Agent 请求'，require_json=true，max_output_tokens=1024。",
        "model_route_plan",
        {"goal": "结构化 Agent 请求", "require_json": True, "max_output_tokens": 1024},
    ),
    (
        "我要复用已有学习产物准备数据集，而不是训练模型：output_dir='./training_runs/v4'，"
        " learning_dirs=['./learning_runs/demo']，dataset_format='messages'。请使用 training_prepare。",
        "training_prepare",
        {
            "output_dir": "./training_runs/v4",
            "learning_dirs": ["./learning_runs/demo"],
            "dataset_format": "messages",
        },
    ),
    (
        "这里的目标是 preparation，不是 model training。请输出 training_prepare："
        " output_dir='./training_runs/v5'，solution_dirs=['./product_runs/solution_library']。",
        "training_prepare",
        {
            "output_dir": "./training_runs/v5",
            "solution_dirs": ["./product_runs/solution_library"],
        },
    ),
    (
        "若要结束任务，必须保留完整 action 外壳。请安全结束，reason='completed'。",
        "finish",
        {"reason": "completed"},
    ),
    (
        "我要查看模型池选择，不是直接生成 route 对象。请输出 model_route_plan，"
        " goal='短请求'，max_output_tokens=128。",
        "model_route_plan",
        {"goal": "短请求", "max_output_tokens": 128},
    ),
)


def build_protocol_examples(*, limit: int | None = None) -> list[dict[str, Any]]:
    """Return deterministic, schema-valid action-protocol SFT rows."""

    rows: list[dict[str, Any]] = []
    for prompt, action, args in _TEMPLATES:
        rows.append(
            {
                "example_id": _stable_id("action_protocol", prompt, action, json.dumps(args, ensure_ascii=False, sort_keys=True)),
                "task_type": "action_protocol_sft",
                "instruction": "你是软件生产 Agent。根据用户请求，只输出一个可执行的 action JSON 对象，不得解释、不得输出思考过程。",
                "input": prompt,
                "output": _canonical_json(action, args),
                "citations": list(_CITATIONS),
                "metadata": {
                    "source": "protocol_catalog",
                    "action": action,
                    "strict_output": True,
                },
            }
        )
    if limit is None or int(limit) <= 0:
        return rows
    return rows[: int(limit)]
