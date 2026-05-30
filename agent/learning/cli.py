"""CLI for the learning pipeline.

函数流程图：
    main()
      -> argparse
      -> --ask 且无输入源 ? ask_learning_run()
         : LearningPipelineConfig -> run_learning_pipeline()
      -> 可选 --ask 对新生成学习库提问
      -> 打印 report/result/answer 路径

你可以继续练算法/工程化的点：
    1. 子命令：现在一个 run 命令；可拆 search/download/index/ask/sandbox。
    2. 运行恢复：可加 run_id、checkpoint、resume。
    3. 配置文件：可支持 YAML/JSON pipeline profile。
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from agent.learning.orchestrator import run_learning_pipeline
from agent.learning.rag_pipeline import benchmark_research_config
from agent.learning.schemas import LearningPipelineConfig
from agent.learning.store import ask_learning_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Learning/RAG/WebSearch pipeline")
    parser.add_argument("--query", default="software agent")
    parser.add_argument("--output", default="./learning_runs/latest")
    parser.add_argument("--local-repo", action="append", default=[], help="本地 repo 路径，可重复")
    parser.add_argument("--github", action="store_true", help="启用 GitHub 网络搜索")
    parser.add_argument("--web", action="store_true", help="启用 Web Search 补充学习")
    parser.add_argument("--repo-limit", type=int, default=3)
    parser.add_argument("--min-stars", type=int, default=0)
    parser.add_argument("--license", action="append", default=[], help="允许的 SPDX license，可重复")
    parser.add_argument("--updated-after", default="")
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--ask", default="", help="对已有或刚生成的 learning output 提问")
    parser.add_argument("--top-k", type=int, default=4, help="RAG 检索返回片段数")
    parser.add_argument("--rag-bm25", action="store_true", help="RAG 检索融合 BM25 + RRF")
    parser.add_argument("--rag-generative", action="store_true", help="使用 LLM 生成回答（需对应 API Key）")
    parser.add_argument("--rag-llm-provider", default="openai", help="生成式 RAG 使用的 provider：openai/groq/deepseek 等")
    parser.add_argument("--rag-llm-model", default="", help="覆盖默认模型；留空则用 provider 默认")
    parser.add_argument(
        "--rag-research",
        action="store_true",
        help="论文级检索管线：多查询 RRF + 混合召回 + 可选 Cross-Encoder + Lost-in-the-Middle（隐式启用 BM25）",
    )
    parser.add_argument("--vector-faiss", action="store_true", help="向量检索使用 FAISS IndexFlatIP（需 pip install faiss-cpu）")
    parser.add_argument(
        "--vector-st",
        action="store_true",
        help="切片向量用 sentence-transformers 稠密嵌入（需 pip install sentence-transformers）",
    )
    parser.add_argument(
        "--vector-st-model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="与 --vector-st 配合的模型名",
    )
    parser.add_argument("--vector-st-batch-size", type=int, default=32, help="SentenceTransformer 建库 batch size")
    parser.add_argument(
        "--vector-hnsw",
        action="store_true",
        help="FAISS 在向量数≥阈值时使用 IndexHNSWFlat（需 --vector-faiss 与 faiss-cpu）",
    )
    parser.add_argument(
        "--vector-hnsw-min",
        type=int,
        default=256,
        help="启用 HNSW 的最小向量条数，低于则仍用 FlatIP",
    )
    parser.add_argument(
        "--eval-gold",
        action="append",
        default=[],
        help="评测用 gold 相对路径，可重复；与 --ask 一起写入 answers 的 metrics",
    )
    parser.add_argument(
        "--vector-openai",
        action="store_true",
        help="建库向量使用 OpenAI embedding（需 OPENAI_API_KEY；与 --vector-st 互斥，优先 OpenAI）",
    )
    parser.add_argument("--vector-openai-model", default="text-embedding-3-small", help="OpenAI embedding 模型名")
    parser.add_argument("--rag-parent-lines", type=int, default=240, help="small-to-big 父块最大行数")
    parser.add_argument("--rag-parent-overlap", type=int, default=40, help="small-to-big 父块重叠行数")
    parser.add_argument(
        "--rag-path-prefix",
        action="append",
        default=[],
        help="与 --rag-research 配合：仅检索相对路径此前缀下的切片，可重复",
    )
    parser.add_argument(
        "--rag-lang",
        action="append",
        default=[],
        help="与 --rag-research 配合：仅保留 metadata language 命中的切片，可重复",
    )
    parser.add_argument(
        "--training-rag-query",
        action="append",
        default=[],
        help="额外导出的 grounded-answer 训练查询，可重复",
    )
    parser.add_argument(
        "--training-rag-query-limit",
        type=int,
        default=1,
        help="导出的 grounded-answer 训练查询上限；超过显式查询后会从知识卡问题中补齐",
    )
    args = parser.parse_args(argv)
    output_dir = Path(args.output)
    has_input_source = bool(args.local_repo or args.github)
    rag_model = args.rag_llm_model.strip() or None
    research = benchmark_research_config() if args.rag_research else None
    if research:
        rp = tuple(str(p).replace("\\", "/").strip() for p in args.rag_path_prefix if str(p).strip())
        rl = tuple(str(x).strip().lower() for x in args.rag_lang if str(x).strip())
        if rp or rl:
            research = replace(research, path_prefixes=rp, languages=rl)
    rag_bm25 = bool(args.rag_bm25) or bool(args.rag_research)
    eval_gold = frozenset(str(p).replace("\\", "/") for p in args.eval_gold if str(p).strip())
    if args.ask.strip() and not has_input_source:
        answer = ask_learning_run(
            output_dir,
            args.ask.strip(),
            top_k=max(int(args.top_k), 1),
            use_bm25=rag_bm25,
            use_generative=bool(args.rag_generative),
            llm_provider=args.rag_llm_provider,
            llm_model=rag_model,
            research=research,
            gold_paths=eval_gold or None,
        )
        print(answer.get("answer", ""))
        print(f"answers: {output_dir.resolve() / 'answers.jsonl'}")
        return 0
    cfg = LearningPipelineConfig(
        query=args.query,
        output_dir=output_dir,
        local_repos=tuple(Path(x) for x in args.local_repo),
        repo_limit=max(int(args.repo_limit), 1),
        min_stars=max(int(args.min_stars), 0),
        allowed_licenses=tuple(args.license),
        updated_after=args.updated_after,
        enable_github_network=bool(args.github),
        enable_web_search=bool(args.web),
        enable_sandbox=not args.no_sandbox,
        vector_use_openai=bool(args.vector_openai),
        vector_openai_model=str(args.vector_openai_model),
        vector_use_faiss=bool(args.vector_faiss),
        vector_use_sentence_transformer=bool(args.vector_st),
        vector_sentence_transformer_model=str(args.vector_st_model),
        vector_st_batch_size=max(1, int(args.vector_st_batch_size)),
        vector_faiss_hnsw=bool(args.vector_hnsw),
        vector_faiss_hnsw_min_vectors=max(8, int(args.vector_hnsw_min)),
        rag_use_bm25=rag_bm25,
        rag_use_generative=bool(args.rag_generative),
        rag_llm_provider=str(args.rag_llm_provider),
        rag_llm_model=str(args.rag_llm_model),
        rag_research=bool(args.rag_research),
        rag_training_queries=tuple(str(x).strip() for x in args.training_rag_query if str(x).strip()),
        rag_training_query_limit=max(0, int(args.training_rag_query_limit)),
        rag_hierarchy_parent_lines=max(40, int(args.rag_parent_lines)),
        rag_hierarchy_parent_overlap_lines=max(0, int(args.rag_parent_overlap)),
    )
    result = run_learning_pipeline(cfg)
    print(f"processed repos: {len(result.repos)}")
    print(f"promoted repos: {result.promoted_repos}")
    print(f"rejected repos: {result.rejected_repos}")
    print(f"vector records: {result.vector_records}")
    print(f"training examples: {result.training_examples}")
    print(f"quality report: {result.quality_report_path}")
    print(f"promotion report: {result.promotion_report_path}")
    print(f"report: {result.report_path}")
    print(f"result: {Path(result.output_dir) / 'result.json'}")
    if args.ask.strip():
        answer = ask_learning_run(
            Path(result.output_dir),
            args.ask.strip(),
            top_k=max(int(args.top_k), 1),
            use_bm25=rag_bm25,
            use_generative=bool(args.rag_generative),
            llm_provider=args.rag_llm_provider,
            llm_model=rag_model,
            research=research,
            gold_paths=eval_gold or None,
        )
        print(answer.get("answer", ""))
        print(f"answers: {Path(result.output_dir) / 'answers.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
