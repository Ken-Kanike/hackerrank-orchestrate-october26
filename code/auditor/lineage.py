"""Lineage graph of recreation paths (OpenLineage / DataHub style): which process copied or restored data into which resource.

Edges come from activities such as
  SYNC_RECORD     integration_service -> search_service   "Active connector repopulated downstream resource search_X"
  RESTORE_BACKUP  backup_service      -> search_service   "Restore job repopulated downstream resource search_X"
A subject's linkage propagates along an edge only when the edge happened at or before the case's audit_at (later copies cannot
change the answer for that case). The edge's activity_id is the citation when no snapshot shows the downstream record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

REPOPULATED = re.compile(r"repopulated downstream resource (\w+?)\.?(?:\s|$)")
KINDS = {"SYNC_RECORD": "connector", "RESTORE_BACKUP": "restore"}


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    time: str
    activity_id: str
    kind: str
    target_system: str


def build_edges(acts: list[dict]) -> list[Edge]:
    out = []
    for a in acts:
        m = REPOPULATED.search(a["details"])
        if m and a["event_type"] in KINDS and a["reported_result"] != "FAILED":
            out.append(Edge(a["resource_id"], m.group(1), a["event_time"], a["activity_id"], KINDS[a["event_type"]], a["target_system"]))
    return sorted(out, key=lambda e: (e.time, e.activity_id))


def downstream(edges: list[Edge], linked: set[str], audit_at: str) -> list[Edge]:
    """Edges (transitively) leaving the linked resources that were already active at audit_at."""
    seen, found, grew = set(linked), [], True
    while grew:
        grew = False
        for e in edges:
            if e.src in seen and e.dst not in seen and e.time <= audit_at:
                seen.add(e.dst); found.append(e); grew = True
    return found
