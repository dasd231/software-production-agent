"""入口：配置、日志、demo / LLM、恢复运行。

函数流程图：
    main()
      -> argparse 定义 CLI
      -> AppConfig.from_env()
      -> CLI 覆盖 config
      -> configure_logging()
      -> 分支：
           --inspect-history-report -> summarize_history_file()
                                    -> should_fail_history()
                                    -> build_history_gate_result()
           --inspect-events         -> summarize/compare events
                                    -> should_fail_inspection()
                                    -> build_gate_result()
                                    -> optional append history
           --demo                   -> ScriptedDemoBrain + run_agent_loop()
           --llm                    -> OpenAIBrain + run_agent_loop()
           else                     -> 返回用法错误

你可以继续练算法/工程化的点：
    1. CLI 分发：现在是 main 内 if 分支；可以拆成 command handler registry。
    2. 参数校验：现在依赖 argparse；可以做跨参数约束校验和更友好的错误提示。
    3. 报告流水线：inspect/history 逻辑相似；可以抽统一 gate/report writer。
    4. 配置合并：现在是 env + CLI；可以加入项目配置文件和优先级解释。
    5. 退出码策略：可以集中定义 exit code enum，避免各分支散落 magic number。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from agent.analytics.events_report import (
    append_history_row,
    build_gate_result,
    build_history_gate_result,
    build_history_summary,
    build_history_row,
    build_events_summary,
    build_report_metadata,
    compare_events_files,
    compare_summaries,
    filter_history_rows,
    load_history_rows,
    load_events,
    save_json,
    save_report_with_metadata,
    should_fail_history,
    should_fail_inspection,
    summarize_history_file,
    summarize_events_file,
)
from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import OpenAIBrain, ScriptedDemoBrain
from agent.llm.providers import resolve_llm_provider
from agent.observability import configure_logging


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent / "prompts"


def main() -> int:
    p = argparse.ArgumentParser(description="软件生产 Agent（AIread 缝合体）")
    p.add_argument("--demo", action="store_true", help="离线闭环演示")
    p.add_argument("--goal", type=str, default="", help="目标描述（LLM 模式）")
    p.add_argument("--workspace", type=str, default="./workspace_demo", help="工作区根目录")
    p.add_argument("--llm", action="store_true", help="OpenAIBrain（需对应 provider 的 API key）")
    p.add_argument(
        "--provider",
        type=str,
        default="",
        choices=["", "openai", "groq", "deepseek", "main_deepseek", "local_deepseek"],
        help="LLM provider",
    )
    p.add_argument("--model", type=str, default="", help="覆盖 Brain/Planner model id")
    p.add_argument("--planner-llm", action="store_true", help="Planner 使用 LLM")
    p.add_argument("--resume", action="store_true", help="从 .agent_state.json 恢复状态再跑（Scripted 脑状态不恢复）")
    p.add_argument(
        "--resume-clear-errors",
        action="store_true",
        help="与 --resume 合用：清空历史 errors 再规划",
    )
    p.add_argument("--events", action="store_true", help="写入 .agent_events.jsonl 结构化事件")
    p.add_argument("--inspect-events", type=str, default="", help="分析事件日志文件（.agent_events.jsonl）")
    p.add_argument("--inspect-baseline", type=str, default="", help="基线事件日志文件，用于与 --inspect-events 对比")
    p.add_argument(
        "--inspect-format",
        type=str,
        default="text",
        choices=["text", "json", "markdown"],
        help="事件报告输出格式",
    )
    p.add_argument("--inspect-save", type=str, default="", help="将 inspect 输出保存到文件")
    p.add_argument("--inspect-output-json", type=str, default="", help="将 inspect gate 结果输出为稳定 JSON 文件")
    p.add_argument("--inspect-history", type=str, default="", help="将 gate 结果追加写入历史 JSONL")
    p.add_argument("--inspect-label", type=str, default="", help="写入历史时的标签（如 branch/pr/env）")
    p.add_argument(
        "--inspect-context-stages",
        type=str,
        default="coding,fixing,investigate",
        help="inspect 阶段化 context gate 目标阶段（逗号分隔，配合 --inspect-fail-on stage_context_missing）",
    )
    p.add_argument("--inspect-history-report", type=str, default="", help="读取历史 JSONL 并输出趋势报告")
    p.add_argument("--history-label", type=str, default="", help="history 报告筛选标签（仅统计该 label）")
    p.add_argument("--history-last", type=int, default=0, help="history 报告仅统计最近 N 条（0=全部）")
    p.add_argument(
        "--inspect-history-fail-on",
        type=str,
        default="",
        choices=["", "regression", "passrate", "duration", "max_duration"],
        help="history 闸门：regression=有退化即失败；passrate=通过率低于阈值失败；duration=平均耗时高于阈值失败；max_duration=最大耗时高于阈值失败",
    )
    p.add_argument("--history-min-pass-rate", type=float, default=80.0, help="history passrate 闸门阈值，默认 80")
    p.add_argument("--history-max-avg-duration", type=float, default=0.0, help="history duration 闸门平均耗时上限秒（0=禁用）")
    p.add_argument("--history-max-duration", type=float, default=0.0, help="history max_duration 闸门单次最大耗时上限秒（0=禁用）")
    p.add_argument(
        "--inspect-fail-on",
        type=str,
        default="",
        choices=["", "critical", "worsened", "no_context_usage", "stage_context_missing"],
        help="inspect 闸门：critical=当前严重级别为critical失败；worsened=对比后严重级别变差失败；no_context_usage=有plan但未命中context提示失败；stage_context_missing=目标阶段有plan但无context命中失败",
    )
    p.add_argument("--policy", type=str, default="", help="额外命令策略 JSON 路径（forbidden_substrings）")
    p.add_argument("--verbose", "-v", action="store_true", help="DEBUG 日志")
    p.add_argument("--max-iter", type=int, default=None, help="覆盖最大循环次数")
    args = p.parse_args()

    cfg = AppConfig.from_env()
    if args.max_iter is not None:
        cfg = replace(cfg, max_agent_iterations=max(int(args.max_iter), 1))
    if args.planner_llm:
        cfg = replace(cfg, planner_use_llm=True)
    if args.provider.strip():
        cfg = replace(cfg, llm_provider=args.provider.strip().lower())
    if args.model.strip():
        cfg = replace(cfg, brain_model=args.model.strip(), planner_model=args.model.strip())
    if args.events:
        cfg = replace(cfg, event_log=True)
    if args.policy.strip():
        cfg = replace(cfg, policy_extra_path=str(Path(args.policy).resolve()))
    if args.resume_clear_errors:
        cfg = replace(cfg, resume_clear_errors=True)

    configure_logging(verbose=args.verbose or cfg.verbose_logging)

    root = Path(args.workspace).resolve()
    prompts = _prompts_dir()

    if args.inspect_history_report.strip():
        history_path = Path(args.inspect_history_report).resolve()
        report_text = summarize_history_file(
            history_path,
            output=args.inspect_format,
            label=args.history_label,
            last_n=max(int(args.history_last), 0),
        )
        print(report_text)
        history_rows = filter_history_rows(
            load_history_rows(history_path),
            label=args.history_label,
            last_n=max(int(args.history_last), 0),
        )
        history_summary = build_history_summary(history_rows)
        history_failed = should_fail_history(
            mode=args.inspect_history_fail_on,
            summary=history_summary,
            min_pass_rate=float(args.history_min_pass_rate),
            max_avg_duration=float(args.history_max_avg_duration),
            max_duration=float(args.history_max_duration),
        )
        if args.inspect_output_json.strip():
            out_path = Path(args.inspect_output_json).resolve()
            gate = build_history_gate_result(
                history_path=history_path,
                mode=args.inspect_history_fail_on,
                min_pass_rate=float(args.history_min_pass_rate),
                max_avg_duration=float(args.history_max_avg_duration),
                max_duration=float(args.history_max_duration),
                failed=history_failed,
                summary=history_summary,
            )
            save_json(out_path, gate)
            print(f"saved gate result: {out_path}")
        if history_failed:
            print(f"history gate failed: {args.inspect_history_fail_on}", file=sys.stderr)
            return 4
        return 0

    if args.inspect_events.strip():
        current_path = Path(args.inspect_events).resolve()
        baseline_path: Path | None = None
        report_text: str
        summary_for_gate: dict | None = None
        comparison_for_gate: dict | None = None
        if args.inspect_baseline.strip():
            baseline_path = Path(args.inspect_baseline).resolve()
            report_text = compare_events_files(current_path, baseline_path, output=args.inspect_format)
            current_summary = build_events_summary(load_events(current_path))
            baseline_summary = build_events_summary(load_events(baseline_path))
            summary_for_gate = current_summary
            comparison_for_gate = compare_summaries(current_summary, baseline_summary)
        else:
            report_text = summarize_events_file(current_path, output=args.inspect_format)
            summary_for_gate = build_events_summary(load_events(current_path))

        print(report_text)
        metadata = build_report_metadata(
            current_path=current_path,
            baseline_path=baseline_path,
            inspect_format=args.inspect_format,
            fail_mode=args.inspect_fail_on,
        )
        if args.inspect_save.strip():
            save_path = Path(args.inspect_save).resolve()
            sidecar = save_report_with_metadata(save_path, report_text, metadata)
            print(f"saved report: {save_path}")
            print(f"saved metadata: {sidecar}")
            print(f"analysis_id: {metadata.get('analysis_id', '')}")
        required_context_stages = [x.strip() for x in args.inspect_context_stages.split(",") if x.strip()]
        failed = should_fail_inspection(
            mode=args.inspect_fail_on,
            summary=summary_for_gate,
            comparison=comparison_for_gate,
            required_stages=required_context_stages,
        )
        if args.inspect_output_json.strip():
            out_path = Path(args.inspect_output_json).resolve()
            gate = build_gate_result(
                analysis_id=str(metadata.get("analysis_id", "")),
                fail_mode=args.inspect_fail_on,
                failed=failed,
                summary=summary_for_gate,
                comparison=comparison_for_gate,
                required_stages=required_context_stages,
            )
            save_json(out_path, gate)
            print(f"saved gate result: {out_path}")
        else:
            gate = build_gate_result(
                analysis_id=str(metadata.get("analysis_id", "")),
                fail_mode=args.inspect_fail_on,
                failed=failed,
                summary=summary_for_gate,
                comparison=comparison_for_gate,
                required_stages=required_context_stages,
            )
        if args.inspect_history.strip():
            history_path = Path(args.inspect_history).resolve()
            report_path = Path(args.inspect_save).resolve() if args.inspect_save.strip() else None
            row = build_history_row(
                gate_result=gate,
                label=args.inspect_label.strip(),
                baseline_path=baseline_path,
                report_path=report_path,
            )
            append_history_row(history_path, row)
            print(f"appended history row: {history_path}")
        if failed:
            print(f"inspect gate failed: {args.inspect_fail_on}", file=sys.stderr)
            return 3
        return 0

    if args.demo:
        goal = "写一个Flask接口 /hello 返回 ok（离线演示）"
        brain: ScriptedDemoBrain | OpenAIBrain = ScriptedDemoBrain(root)
        run_agent_loop(goal, root, prompts, brain, config=cfg, resume=args.resume)
        print("demo finished; workspace:", root)
        return 0

    if args.llm:
        goal = args.goal or "写一个最小的 Flask 接口 /hello 返回 ok"
        model_hint = args.model.strip() if args.model.strip() else (cfg.brain_model if cfg.llm_provider == "openai" else "")
        provider = resolve_llm_provider(cfg.llm_provider, model_hint)
        brain = OpenAIBrain(prompts, model=provider.model, provider=provider.name)
        run_agent_loop(goal, root, prompts, brain, config=cfg, resume=args.resume)
        print("llm run finished; workspace:", root)
        return 0

    print("请指定 --demo 或 --llm（并设置对应 provider 的 API key）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
