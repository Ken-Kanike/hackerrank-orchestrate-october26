"""Run events for live monitoring (web UI, tracing). A no-op unless a sink is installed, so the CLI and its output are unaffected.

Event kinds: stage_start / stage_end (id, ms, stats), progress (stage, done, total), log (level, msg), llm (task, provider, model, tokens, ms, ok, cached).
"""
from __future__ import annotations

import time
from contextlib import contextmanager

_sink = None


def set_sink(fn) -> None:
    global _sink
    _sink = fn


def emit(kind: str, **data) -> None:
    if _sink is not None:
        try:
            _sink({"t": time.time(), "kind": kind, **data})
        except Exception:                      # monitoring must never break a run
            pass


def log(level: str, msg: str) -> None:
    emit("log", level=level, msg=msg)


@contextmanager
def stage(sid: str, **meta):
    """Times a pipeline stage; the body may fill `stats` (dict) that is attached to the stage_end event."""
    stats: dict = {}
    t0 = time.perf_counter()
    emit("stage_start", id=sid, **meta)
    try:
        yield stats
    except Exception as e:
        emit("stage_end", id=sid, ms=round((time.perf_counter() - t0) * 1000), ok=False, error=str(e)[:200], **stats)
        raise
    emit("stage_end", id=sid, ms=round((time.perf_counter() - t0) * 1000), ok=True, **stats)
