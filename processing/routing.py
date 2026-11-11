"""Route validated records to trusted/ or quarantine/.

trusted/    only ACCEPTED records, with typed values and lineage columns
            (run_id, ingested_at, source_row).
quarantine/ every REJECTED or FLAGGED record with its ORIGINAL text values,
            status, reason codes and full explanations - nothing is dropped
            silently. A JSON Lines copy keeps the structured reasons.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from config import settings as S
from ingestion.loader import IngestionBatch, _rel
from security.validator import ACCEPTED, RecordResult


def route(results: list[RecordResult], batch: IngestionBatch,
          trusted_dir: Path = S.TRUSTED_DIR, quarantine_dir: Path = S.QUARANTINE_DIR) -> dict:
    trusted_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    trusted_rows, quarantine_rows = [], []
    for r in results:
        if r.status == ACCEPTED:
            m = r.model
            trusted_rows.append({
                "record_id": m.record_id, "source_id": m.source_id,
                "timestamp": m.timestamp.strftime(S.TIMESTAMP_FORMAT), "category": m.category,
                "quantity": m.quantity, "unit_price": m.unit_price, "amount": m.amount,
                "currency": m.currency, "run_id": batch.run_id, "ingested_at": batch.ingested_at,
                "source_row": r.row_number,
            })
        else:
            row = {"source_row": r.row_number, "status": r.status}
            row.update({f: r.raw.get(f, "") for f in S.FIELDS})
            row["reason_codes"] = ";".join(dict.fromkeys(x.code for x in r.reasons))
            row["controls"] = ";".join(dict.fromkeys(x.control for x in r.reasons))
            row["reasons"] = " | ".join(x.message for x in r.reasons)
            row["run_id"] = batch.run_id
            quarantine_rows.append((row, r))

    trusted_cols = ["record_id", "source_id", "timestamp", "category", "quantity", "unit_price", "amount",
                    "currency", "run_id", "ingested_at", "source_row"]
    trusted_path = trusted_dir / "trusted_transactions.csv"
    pd.DataFrame(trusted_rows, columns=trusted_cols).to_csv(trusted_path, index=False)

    q_cols = ["source_row", "status", *S.FIELDS, "reason_codes", "controls", "reasons", "run_id"]
    quarantine_path = quarantine_dir / "quarantined_records.csv"
    pd.DataFrame([q for q, _ in quarantine_rows], columns=q_cols).to_csv(quarantine_path, index=False)

    jsonl_path = quarantine_dir / "quarantined_records.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as fh:
        for q, r in quarantine_rows:
            fh.write(json.dumps({"run_id": batch.run_id, "source_row": r.row_number, "status": r.status,
                                 "record": {f: r.raw.get(f, "") for f in S.FIELDS},
                                 "reasons": [x.as_dict() for x in r.reasons]}) + "\n")

    return {"trusted_file": _rel(trusted_path),
            "quarantine_file": _rel(quarantine_path),
            "quarantine_jsonl": _rel(jsonl_path),
            "trusted_count": len(trusted_rows), "quarantine_count": len(quarantine_rows)}
