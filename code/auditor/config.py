"""Paths and environment loading. No third-party dependencies."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "dataset"
CACHE_DIR = REPO_ROOT / "code" / ".cache"
OUTPUT_CSV = REPO_ROOT / "output.csv"


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ (existing env vars win)."""
    path = path or REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v and not os.environ.get(k.strip()):
            os.environ[k.strip()] = v


# ---- tunables (each documents where it comes from; evaluation_report.md has the ablation) ----
# Two-tier time model: record *discovery* may use any record stamped <= audit_at even from a later export; record *state* is decided
# from files captured <= audit_at (citable). Later files decide state only when nothing citable exists (step is then flagged).
STRICT_TIME = os.environ.get("AUDIT_STRICT_TIME", "1") == "1"
# Lineage propagation: a resource recreated by a connector / restore job (edge time <= audit_at) joins the subject's case.
USE_LINEAGE = os.environ.get("AUDIT_LINEAGE", "1") == "1"
# Activity-stream state checks (CHECK_DATA_FLOW / CHECK_RESTORE_ACCESS) as weak observations.
USE_ACTIVITY_CHECKS = os.environ.get("AUDIT_ACTIVITY_CHECKS", "1") == "1"
# Workflow-run reconstruction: the account-delete of a run and its sibling actions share a learned second-offset pattern.
# This exploits a regularity of the supplied logs (see limitations A2); evidence-based signals always run first.
USE_RUN_ALIGNMENT = os.environ.get("AUDIT_RUN_ALIGNMENT", "1") == "1"
# How residual ambiguity (several equally plausible accounts) is resolved: "earliest" (legacy) or "nearest" (closest to reported_at).
TIE_BREAK = os.environ.get("AUDIT_TIE_BREAK", "earliest")
# Ghost sweep: grep all evidence text for the subject's identifiers; unexplained resources become review flags (never silent edits).
USE_GHOST_SWEEP = os.environ.get("AUDIT_GHOST_SWEEP", "1") == "1"
# Multi-case users: evidence older than requested_at - 1 day is assigned to the user's earlier request. For users with a single
# request there is no earlier request, so the cut-off must not discard their pre-request evidence (limitations D4).
PARTITION_SINGLE_CASE_USERS_ONLY = os.environ.get("AUDIT_PARTITION_MULTI_ONLY", "1") == "1"
# Investigator agent (tool loop on ambiguous links). Advisory by default: it writes review notes but never changes the output.
USE_INVESTIGATOR = os.environ.get("AUDIT_INVESTIGATOR", "1") == "1"
INVESTIGATOR_APPLY = os.environ.get("AUDIT_INVESTIGATOR_APPLY", "0") == "1"
