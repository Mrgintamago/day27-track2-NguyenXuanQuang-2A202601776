"""Dataset- and column-level lineage traversal.

Blast radius is the question "who else is wrong right now?", and it has to be
answerable in seconds during an incident. Two properties matter more than
elegance here:

- **transitive**: the starter's column traversal returned only direct children,
  so a two-hop dependency (the RAG index, the support agent) was invisible;
- **cycle-safe**: real lineage graphs pick up cycles through bad exports or a
  self-referencing incremental model, and a traversal that loops forever during
  an incident is worse than no traversal at all.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Iterable


def load_graph(path: str | Path) -> dict[str, list[str]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload["dataset_lineage"] if "dataset_lineage" in payload else payload


def _bfs_descendants(graph: dict[str, Iterable[str]], start: str) -> list[str]:
    """Breadth-first transitive closure, excluding ``start`` itself.

    BFS (not DFS) on purpose: results come out nearest-first, which is the
    order an on-call wants to triage in. ``seen`` is seeded with ``start`` so a
    cycle back to the origin terminates and never reports the origin as its own
    downstream.
    """
    if not isinstance(graph, dict) or start not in graph and not graph.get(start):
        # Unknown node: no downstream, no exception. During an incident a typo
        # must return "nothing found", not a traceback.
        if not isinstance(graph, dict) or start not in graph:
            return []

    seen = {start}
    queue: deque[str] = deque([start])
    out: list[str] = []
    while queue:
        node = queue.popleft()
        children = graph.get(node)
        for child in [] if children is None else children:
            if child not in seen:
                seen.add(child)
                out.append(child)
                queue.append(child)
    return out


def get_downstream_assets(graph: dict[str, list[str]], start: str) -> list[str]:
    """Return transitive downstream assets in BFS order, excluding start."""
    return _bfs_descendants(graph, start)


def get_column_downstream(column_graph: dict[str, list[str]], start_column: str) -> list[str]:
    """Transitive column-level downstream.

    Graph shape is ``{"model.column": ["model.column", ...]}``. Column lineage
    answers a sharper question than dataset lineage: `stg_orders` breaking does
    not mean every downstream column is wrong - only the ones actually fed by
    the broken column. That is the difference between "the dashboard is
    suspect" and "the revenue tile is wrong, the order-count tile is fine".
    """
    return _bfs_descendants(column_graph, start_column)


def get_upstream_assets(graph: dict[str, list[str]], target: str) -> list[str]:
    """Transitive *upstream* of a node - the root-cause search space.

    Downstream answers "who did I break?"; upstream answers "who broke me?",
    which is the question you actually start an investigation with.
    """
    reverse: dict[str, list[str]] = {}
    for parent, children in (graph or {}).items():
        for child in [] if children is None else children:
            reverse.setdefault(child, []).append(parent)
        reverse.setdefault(parent, reverse.get(parent, []))
    return _bfs_descendants(reverse, target)


def blast_radius(
    dataset_graph: dict[str, list[str]],
    column_graph: dict[str, list[str]] | None,
    start: str,
    start_column: str | None = None,
) -> dict[str, Any]:
    """One incident-shaped summary instead of three separate calls."""
    return {
        "start": start,
        "downstream_assets": get_downstream_assets(dataset_graph, start),
        "upstream_assets": get_upstream_assets(dataset_graph, start),
        "downstream_columns": (
            get_column_downstream(column_graph or {}, start_column) if start_column else []
        ),
    }


def extract_dbt_dataset_graph(manifest_path: str | Path) -> dict[str, list[str]]:
    """Parse dbt's manifest into a dataset lineage graph.

    Reading the manifest beats a hand-maintained JSON file: the graph is
    generated from the code that actually ran, so it cannot drift out of date
    the way ``data/baseline/lineage_graph.json`` can.

    Node ids are shortened (``model.project.stg_orders`` -> ``stg_orders``) so
    the output is comparable with the hand-written baseline graph. Test nodes
    are dropped - they are not data assets and would swamp the blast radius.
    """
    path = Path(manifest_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    def is_asset(node_id: str) -> bool:
        return node_id.split(".")[0] in {"model", "seed", "source", "snapshot", "exposure"}

    def short(node_id: str) -> str:
        return node_id.split(".")[-1]

    graph: dict[str, list[str]] = {}
    for parent, children in (manifest.get("child_map") or {}).items():
        if not is_asset(parent):
            continue
        kept = [short(c) for c in children if is_asset(c)]
        graph.setdefault(short(parent), [])
        for child in kept:
            if child not in graph[short(parent)]:
                graph[short(parent)].append(child)
    return graph
