# ─────────────────────────────────────────────────────────────────────────────
# Ghost Data Still Exists — API server (Render / Docker)
#
# Wraps the existing deletion-audit CLI in a minimal FastAPI HTTP server.
# Endpoints are intentionally read-only; no dataset files are exposed.
# Secrets come from environment variables only, never from this file.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

# Make 'code/' importable regardless of cwd
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code"))

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    from pydantic import BaseModel
except ImportError as exc:
    raise RuntimeError(
        "FastAPI not installed. Run: pip install fastapi uvicorn[standard]"
    ) from exc

from auditor.config import load_env, DATASET, OUTPUT_CSV  # noqa: E402
from auditor.llm.router import Router  # noqa: E402
from auditor.pipeline import read_requests, run, write_csv  # noqa: E402

load_env()

app = FastAPI(
    title="Ghost Data Still Exists — Deletion Audit API",
    description=(
        "AI-powered deletion-audit agent. POST /audit to run the full pipeline "
        "against the supplied dataset. GET /output to download the last result."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── shared state (single-worker, suitable for Render free tier) ───────────────
_last_run: dict = {}


class AuditRequest(BaseModel):
    mode: str = "hybrid"          # "hybrid" or "offline"
    use_vision: bool = True
    data_dir: Optional[str] = None  # overrides default dataset path
    limit: Optional[int] = None     # process only the first N cases (testing)


@app.get("/", summary="Health check")
def health():
    return {
        "status": "ok",
        "service": "ghost-data-still-exists",
        "dataset_present": DATASET.exists(),
        "output_present": OUTPUT_CSV.exists(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.post("/audit", summary="Run the deletion-audit pipeline")
def audit(req: AuditRequest):
    """
    Runs the full deletion-audit pipeline and returns a summary.
    The output.csv is also written to disk; use GET /output to download it.

    Note: a full 518-case hybrid run takes 2–5 minutes depending on LLM latency.
    Use `mode=offline` for a deterministic, seconds-fast run.
    """
    data = Path(req.data_dir) if req.data_dir else DATASET
    if not data.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Dataset directory not found: {data}. "
                "Mount the dataset/ folder into the container or set data_dir."
            ),
        )

    router = Router(enabled=req.mode == "hybrid")
    reqs = read_requests("deletion_requests.csv", data)
    if req.limit:
        reqs = reqs[: req.limit]

    pool = reqs
    samples_path = data / "sample_deletion_requests.csv"
    if samples_path.exists():
        pool = reqs + read_requests("sample_deletion_requests.csv", data)

    rows, report, _, _ = run(reqs, pool, router, data, use_vision=req.use_vision)
    write_csv(rows, OUTPUT_CSV)

    from collections import Counter
    status_counts = dict(Counter(r["deletion_status"] for r in rows))

    _last_run.update(
        {
            "run_id": router.run_id,
            "cases": len(rows),
            "mode": req.mode,
            "status_counts": status_counts,
            "validator_flags": len(report["flags"]),
            "ambiguous_links": len(report["ambiguous"]),
            "llm_calls": router.calls,
            "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )

    return JSONResponse(
        content={
            "summary": _last_run,
            "flags": [{"case_id": c, "errors": e} for c, e in report["flags"][:20]],
            "output_available": True,
            "download": "/output",
        }
    )


@app.get("/output", summary="Download output.csv")
def download_output():
    """Download the output.csv produced by the last /audit run."""
    if not OUTPUT_CSV.exists():
        raise HTTPException(
            status_code=404,
            detail="output.csv not found. Run POST /audit first.",
        )
    return FileResponse(
        path=str(OUTPUT_CSV),
        media_type="text/csv",
        filename="output.csv",
    )


@app.get("/status", summary="Status of the last run")
def status():
    if not _last_run:
        return {"status": "no_run", "message": "POST /audit to start a run."}
    return _last_run


@app.get("/cases/{case_id}", summary="Single-case audit result")
def get_case(case_id: str):
    """Return the output row for a specific case_id from the last run."""
    if not OUTPUT_CSV.exists():
        raise HTTPException(status_code=404, detail="No output.csv yet.")
    import csv
    with OUTPUT_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["case_id"] == case_id:
                row["steps"] = json.loads(row["steps_json"])
                return row
    raise HTTPException(status_code=404, detail=f"case_id {case_id!r} not found.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=False,
    )
