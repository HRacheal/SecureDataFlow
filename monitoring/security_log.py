"""Security logging.

logs/security_events.jsonl - one event per failed check (append-only)
logs/ingestion_runs.jsonl  - one summary line per ingestion run (append-only)
logs/pipeline.log          - human-readable operational log

Note: these files are ordinary append-only files. They are not protected
against an administrator editing them (no hash chaining or remote log
shipping) - see the report's limitations section.
"""

from __future__ import annotations

import json
import logging
from collections import Counter

from config import settings as S
from ingestion.loader import IngestionBatch
from security.validator import ACCEPTED, FLAGGED, REJECTED, RecordResult

EVENTS_FILE = S.LOG_DIR / "security_events.jsonl"
RUNS_FILE = S.LOG_DIR / "ingestion_runs.jsonl"
PIPELINE_LOG = S.LOG_DIR / "pipeline.log"


def get_logger() -> logging.Logger:
    S.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("securedataflow")
    if not log.handlers:
        log.setLevel(logging.INFO)
        h = logging.FileHandler(PIPELINE_LOG, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.propagate = False
    return log


def summarise(results: list[RecordResult]) -> dict:
    status = Counter(r.status for r in results)
    codes = Counter(x.code for r in results for x in r.reasons)
    controls = Counter(x.control for r in results for x in r.reasons)
    # records (not reasons) per control: a record with 2 type errors counts once
    records_per_control = Counter(c for r in results for c in {x.control for x in r.reasons})
    return {
        "received": len(results),
        "accepted": status.get(ACCEPTED, 0),
        "rejected": status.get(REJECTED, 0),
        "flagged": status.get(FLAGGED, 0),
        "quarantined": status.get(REJECTED, 0) + status.get(FLAGGED, 0),
        "failures_by_reason_code": dict(codes.most_common()),
        "failures_by_control": dict(controls.most_common()),
        "records_failing_each_control": dict(records_per_control.most_common()),
    }


def write_logs(batch: IngestionBatch, results: list[RecordResult], routing: dict) -> dict:
    log = get_logger()
    summary = summarise(results)
    with open(EVENTS_FILE, "a", encoding="utf-8") as fh:
        for r in results:
            for x in r.reasons:
                fh.write(json.dumps({
                    "run_id": batch.run_id, "ingested_at": batch.ingested_at, "source_file": batch.source_file,
                    "source_row": r.row_number, "record_id": r.raw.get("record_id", ""),
                    "source_id": r.raw.get("source_id", ""), "decision": r.status, **x.as_dict(),
                }) + "\n")
    run = {**batch.metadata(), **summary, **routing}
    with open(RUNS_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(run) + "\n")
    log.info("run=%s file=%s sha256=%s received=%d accepted=%d rejected=%d flagged=%d",
             batch.run_id, batch.source_file, batch.sha256, summary["received"], summary["accepted"],
             summary["rejected"], summary["flagged"])
    for code, n in summary["failures_by_reason_code"].items():
        log.warning("run=%s validation_failure code=%s count=%d", batch.run_id, code, n)
    return run
