"""Data ingestion.

``secure_ingest`` - used with security controls (Experiment B):
  * assigns a run id and records ingestion time (UTC) and source
  * fingerprints the received file (SHA-256) and stores an archive copy,
    re-hashing the copy to confirm it is identical
  * reads every value as *text* (no silent type conversion) so the
    validation layer sees exactly what was sent

``naive_ingest`` - the typical "just load it" approach (Experiment A):
  pandas guesses types, unparseable numbers silently become NaN, nothing
  is checked.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import settings as S
from security.integrity import sha256_file


@dataclass
class IngestionBatch:
    run_id: str
    ingested_at: str
    source_file: str
    source_label: str
    sha256: str
    archive_file: str
    archive_verified: bool
    columns: list[str]
    missing_columns: list[str]
    unexpected_columns: list[str]
    records: list[dict]

    @property
    def received(self) -> int:
        return len(self.records)

    def metadata(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "records"}
        d["records_received"] = self.received
        return d


def secure_ingest(path: Path, source_label: str = "batch upload") -> IngestionBatch:
    path = Path(path)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    digest = sha256_file(path)
    S.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive = S.ARCHIVE_DIR / f"{run_id}__{path.name}"
    shutil.copy2(path, archive)
    archive_ok = sha256_file(archive) == digest

    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)
    cols = list(df.columns)
    records = df.to_dict(orient="records")
    return IngestionBatch(
        run_id=run_id, ingested_at=ingested_at, source_file=_rel(path), source_label=source_label,
        sha256=digest, archive_file=_rel(archive), archive_verified=archive_ok, columns=cols,
        missing_columns=[c for c in S.FIELDS if c not in cols],
        unexpected_columns=[c for c in cols if c not in S.FIELDS], records=records,
    )


def naive_ingest(path: Path) -> pd.DataFrame:
    """No controls: default pandas parsing; bad numbers -> NaN; duplicates kept."""
    df = pd.read_csv(path)
    for col in ("quantity", "unit_price", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(S.PROJECT_ROOT))
    except ValueError:
        return str(p)
