"""Knowledge card generator.

函数流程图：
    build_knowledge_cards(repo, readme, structure, slices)
      -> overview card from README
      -> setup card from package files
      -> architecture card from languages/entrypoints/tests
      -> notable code cards from high-token slices
      -> list[KnowledgeCard]

你可以继续练算法/工程化的点：
    1. 卡片聚类：现在是规则生成；可按 embedding 聚类成主题卡。
    2. 问题生成：现在是模板问题；可接 LLM 生成学习题/检索题/SFT 样本。
    3. 质量控制：可加入引用覆盖率、事实一致性和重复卡片合并。
"""

from __future__ import annotations

from agent.learning.schemas import CodeSlice, KnowledgeCard, ParsedReadme, RepoCandidate, StructureSummary


def _top_tokens(slices: list[CodeSlice], limit: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    for sl in slices:
        for token in sl.tokens:
            counts[token] = counts.get(token, 0) + 1
    return [token for token, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]]


def build_knowledge_cards(
    repo: RepoCandidate,
    readme: ParsedReadme,
    structure: StructureSummary,
    slices: list[CodeSlice],
) -> list[KnowledgeCard]:
    cards: list[KnowledgeCard] = []
    title = readme.title or repo.name
    summary = readme.summary or repo.description or f"{repo.full_name} source repository"
    cards.append(
        KnowledgeCard(
            title=f"{title}: overview",
            summary=summary[:700],
            tags=["overview", *list(repo.topics[:4])],
            source_paths=[readme.path] if readme.path else [],
            questions=[
                f"{title} 是什么？",
                f"{title} 的主要功能是什么？",
                "这个项目适合学习哪些实现方式？",
            ],
        )
    )
    if structure.package_files:
        cards.append(
            KnowledgeCard(
                title=f"{title}: setup and dependencies",
                summary="Detected package/config files: " + ", ".join(structure.package_files[:12]),
                tags=["setup", "dependencies"],
                source_paths=structure.package_files[:12],
                questions=["如何安装和运行这个项目？", "这个项目依赖哪些生态？"],
            )
        )
    cards.append(
        KnowledgeCard(
            title=f"{title}: architecture map",
            summary=(
                f"Languages: {structure.languages}. Entrypoints: {structure.entrypoints[:8]}. "
                f"Tests: {structure.tests[:8]}."
            ),
            tags=["architecture", "structure", *_top_tokens(slices, 5)],
            source_paths=structure.entrypoints[:8] + structure.tests[:8],
            questions=["项目目录结构是什么？", "入口文件和测试文件在哪里？"],
        )
    )
    for sl in sorted(slices, key=lambda x: len(x.tokens), reverse=True)[:3]:
        cards.append(
            KnowledgeCard(
                title=f"Code slice: {sl.path}:{sl.start_line}",
                summary=sl.text.strip().replace("\n", " ")[:500],
                tags=["code", sl.language, *list(sl.tokens[:5])],
                source_paths=[sl.path],
                questions=[f"{sl.path} 这段代码在做什么？", "这段代码能复用到什么场景？"],
            )
        )
    return cards
