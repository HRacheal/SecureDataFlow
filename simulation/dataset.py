"""Synthetic, entirely fictional transaction data.

Two datasets are produced with different random seeds:

* ``data/raw/transactions_clean.csv``  - the October 2026 batch that the
  sources legitimately send (1,000 records). The attack simulation starts
  from a copy of this file; the file itself is never modified.
* ``data/reference/historical_transactions.csv`` - July-September 2026
  history (5,000 records) from which the anomaly-detection baseline is
  built. Keeping the baseline separate from the incoming batch means an
  attacker who poisons the batch cannot also shift the yardstick used to
  judge it.

Records are generic (source, time, category, quantity, price, amount) so the
same structure fits retail, wholesale, e-commerce or other industries.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from config import settings as S
from security.integrity import sign_record

# Per-category generating parameters (fictional, KES).
CATEGORY_PROFILES = {
    #               weight, median unit price, log-sigma, poisson lambda for extra quantity
    "Groceries":   (0.35,    350.0, 0.55, 3.0),
    "Clothing":    (0.20,   1800.0, 0.50, 1.0),
    "Household":   (0.20,   2500.0, 0.60, 1.0),
    "Electronics": (0.15,  22000.0, 0.70, 0.3),
    "Stationery":  (0.10,    200.0, 0.55, 4.0),
}
SOURCE_WEIGHTS = {"SRC-001": 0.25, "SRC-002": 0.25, "SRC-003": 0.25, "SRC-004": 0.10, "SRC-005": 0.15}


def generate_records(n: int, seed: int, start: datetime, end: datetime, id_year: int, id_offset: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    cats = list(CATEGORY_PROFILES)
    cat_w = np.array([CATEGORY_PROFILES[c][0] for c in cats])
    srcs = list(SOURCE_WEIGHTS)
    src_w = np.array(list(SOURCE_WEIGHTS.values()))

    span = int((end - start).total_seconds())
    offsets = np.sort(rng.integers(0, span, size=n))

    records = []
    for i in range(n):
        cat = cats[rng.choice(len(cats), p=cat_w)]
        _, median, sigma, lam = CATEGORY_PROFILES[cat]
        unit_price = round(float(np.exp(np.log(median) + rng.normal(0, sigma))), 2)
        unit_price = max(unit_price, 1.00)
        quantity = int(min(1 + rng.poisson(lam), 50))
        amount = round(quantity * unit_price, 2)
        rec = {
            "record_id": f"TXN-{id_year}-{id_offset + i + 1:06d}",
            "source_id": srcs[rng.choice(len(srcs), p=src_w)],
            "timestamp": (start + timedelta(seconds=int(offsets[i]))).strftime(S.TIMESTAMP_FORMAT),
            "category": cat,
            "quantity": str(quantity),
            "unit_price": f"{unit_price:.2f}",
            "amount": f"{amount:.2f}",
            "currency": "KES",
        }
        rec["signature"] = sign_record(rec)
        records.append(rec)
    return records


def write_csv(records: list[dict], path: Path, fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or S.FIELDS
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(records)


def read_csv_raw(path: Path) -> list[dict]:
    """Read a CSV keeping every value as the exact text received."""
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def generate_all() -> dict:
    clean = generate_records(S.N_CLEAN_RECORDS, S.CLEAN_SEED, S.BATCH_WINDOW_START, S.BATCH_WINDOW_END, 2026)
    write_csv(clean, S.CLEAN_FILE)
    hist = generate_records(S.N_HISTORICAL_RECORDS, S.HISTORICAL_SEED, S.HISTORICAL_WINDOW_START,
                            S.HISTORICAL_WINDOW_END, 2026, id_offset=500000)
    write_csv(hist, S.HISTORICAL_FILE)
    return {"clean_records": len(clean), "historical_records": len(hist)}


if __name__ == "__main__":
    print(generate_all())
