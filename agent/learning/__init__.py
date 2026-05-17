"""Learning pipeline package: GitHub/Web/RAG/sandbox orchestration.

函数流程图：
    用户 query / local repo
      -> github_search
      -> repo_downloader
      -> filters
      -> readme_parser
      -> structure_parser
      -> code_slicer
      -> vector_store
      -> knowledge_cards
      -> rag_qa
      -> web_search
      -> sandbox
      -> orchestrator

你可以继续练算法/工程化的点：
    1. 编排策略：现在是顺序 pipeline；可以升级成 DAG + cache + retry。
    2. 数据质量：可以给 repo/readme/slice/card 增加置信度与去重。
    3. 训练闭环：当前产出检索库和知识卡；后续可导出 SFT/DPO 样本。
"""

from __future__ import annotations

