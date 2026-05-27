from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from agent.graph_runtime.property_graph import PropertyGraph


GraphDialect = Literal["neo4j", "memgraph"]


class GraphStoreAdapter(Protocol):
    name: str

    def export(self, graph: PropertyGraph) -> dict[str, Any]:
        """Return a side-effect-free import bundle for a graph store."""


@dataclass(slots=True)
class CypherGraphStoreAdapter:
    """Neo4j/Memgraph-oriented adapter without runtime dependency.

    Production can replace this with a Bolt/HTTP adapter. Keeping this exporter
    dependency-free makes tests deterministic and keeps local machines light.
    """

    dialect: GraphDialect = "neo4j"
    name: str = "cypher-file"

    def export(self, graph: PropertyGraph) -> dict[str, Any]:
        return render_cypher_import_bundle(graph, dialect=self.dialect)


def _constraint(label: str, prop: str, *, dialect: GraphDialect) -> str:
    if dialect == "memgraph":
        return f"CREATE CONSTRAINT ON (n:{label}) ASSERT n.{prop} IS UNIQUE;"
    return f"CREATE CONSTRAINT {label.lower()}_{prop}_unique IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE;"


def _index(label: str, prop: str, *, dialect: GraphDialect) -> str:
    if dialect == "memgraph":
        return f"CREATE INDEX ON :{label}({prop});"
    return f"CREATE INDEX {label.lower()}_{prop}_idx IF NOT EXISTS FOR (n:{label}) ON (n.{prop});"


def render_cypher_import_bundle(graph: PropertyGraph, *, dialect: GraphDialect = "neo4j") -> dict[str, Any]:
    labels = sorted({label for node in graph.nodes.values() for label in node.labels})
    constraints: list[str] = []
    indexes: list[str] = []
    if "AgentRun" in labels:
        constraints.append(_constraint("AgentRun", "run_id", dialect=dialect))
        indexes.append(_index("AgentRun", "status", dialect=dialect))
    if "PolicyVersion" in labels:
        constraints.append(_constraint("PolicyVersion", "version", dialect=dialect))
    if "Artifact" in labels:
        indexes.append(_index("Artifact", "checksum", dialect=dialect))
        indexes.append(_index("Artifact", "path", dialect=dialect))
    if "Action" in labels:
        indexes.append(_index("Action", "action", dialect=dialect))
        indexes.append(_index("Action", "ok", dialect=dialect))
    if "Decision" in labels:
        indexes.append(_index("Decision", "route_key", dialect=dialect))
    if "Evidence" in labels:
        indexes.append(_index("Evidence", "path", dialect=dialect))
    if "HumanReview" in labels:
        indexes.append(_index("HumanReview", "level", dialect=dialect))
    if "SimilarityCollapse" in labels:
        indexes.append(_index("SimilarityCollapse", "alarm", dialect=dialect))
        indexes.append(_index("SimilarityCollapse", "severity", dialect=dialect))

    return {
        "schema": "graph_store_import_bundle.v1",
        "dialect": dialect,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "constraints": constraints,
        "indexes": indexes,
        "cypher": graph.to_cypher_seed(),
        "apply_order": ["constraints", "indexes", "cypher"],
        "safety": {
            "side_effect_free": True,
            "requires_manual_apply": True,
            "notes": [
                "Generated bundle is for review/import; this code does not open a database connection.",
                "Use a staging graph database first; production import should be idempotent and backed up.",
            ],
        },
    }


def build_graph_store_adapter_plan() -> dict[str, Any]:
    return {
        "schema": "graph_store_adapter_plan.v1",
        "adapters": [
            {
                "name": "InMemoryPropertyGraph",
                "status": "implemented",
                "purpose": "unit tests, deterministic local Graph-RAG and no external service dependency",
            },
            {
                "name": "CypherGraphStoreAdapter",
                "status": "implemented",
                "dialects": ["neo4j", "memgraph"],
                "purpose": "constraints/indexes/Cypher import bundle for real graph databases",
            },
            {
                "name": "BoltGraphStoreAdapter",
                "status": "planned",
                "purpose": "real online writes through official Neo4j/Memgraph drivers",
            },
        ],
        "write_path": [
            "agent_events_jsonl",
            "agent_events_to_property_graph",
            "render_cypher_import_bundle",
            "manual/staged graph DB apply",
            "future Bolt streaming writer",
        ],
    }
