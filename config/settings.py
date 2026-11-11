"""Central configuration for SecureDataFlow.

Everything the pipeline treats as policy (allowed values, ranges, thresholds,
time window, file locations) lives here so that rules are visible in one place
and are not scattered through the code.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"                # clean synthetic source data (never modified by attacks)
REFERENCE_DIR = DATA_DIR / "reference"    # historical data + baseline profile used by anomaly checks
ATTACKED_DIR = DATA_DIR / "attacked"      # incoming batch after attack simulation + ground-truth manifest
ARCHIVE_DIR = DATA_DIR / "archive"        # immutable copy of every ingested file (evidence)
TRUSTED_DIR = DATA_DIR / "trusted"        # records that passed validation
QUARANTINE_DIR = DATA_DIR / "quarantine"  # rejected + flagged records with reasons
LOG_DIR = PROJECT_ROOT / "logs"
REPORTS_DIR = PROJECT_ROOT / "reports"

CLEAN_FILE = RAW_DIR / "transactions_clean.csv"
HISTORICAL_FILE = REFERENCE_DIR / "historical_transactions.csv"
BASELINE_FILE = REFERENCE_DIR / "baseline_profile.json"
ATTACKED_FILE = ATTACKED_DIR / "transactions_incoming_attacked.csv"
MANIFEST_FILE = ATTACKED_DIR / "attack_manifest.csv"

# --------------------------------------------------------------------------
# Record schema / policy
# --------------------------------------------------------------------------
FIELDS = [
    "record_id", "source_id", "timestamp", "category",
    "quantity", "unit_price", "amount", "currency", "signature",
]
REQUIRED_FIELDS = FIELDS  # every field is mandatory, including the signature
SIGNED_FIELDS = [f for f in FIELDS if f != "signature"]

RECORD_ID_PATTERN = r"^TXN-\d{4}-\d{6}$"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"          # ISO 8601, UTC, second precision
TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"

# Registered data sources (fictional). A record from any other source is rejected.
ALLOWED_SOURCES = {
    "SRC-001": "Branch POS system - North",
    "SRC-002": "Branch POS system - South",
    "SRC-003": "E-commerce web checkout",
    "SRC-004": "Wholesale order portal",
    "SRC-005": "Partner marketplace feed",
}
ALLOWED_CATEGORIES = ["Electronics", "Groceries", "Clothing", "Household", "Stationery"]
ALLOWED_CURRENCIES = ["KES"]

# Hard limits: values outside these are *invalid* (business rules, not statistics).
QUANTITY_MIN, QUANTITY_MAX = 1, 1000
UNIT_PRICE_MIN, UNIT_PRICE_MAX = 1.00, 1_000_000.00
AMOUNT_TOLERANCE = 0.01  # |amount - quantity*unit_price| must not exceed this (rounding)

# The batch being ingested covers October 2026. Timestamps outside are rejected.
BATCH_WINDOW_START = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
BATCH_WINDOW_END = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
HISTORICAL_WINDOW_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
HISTORICAL_WINDOW_END = datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc)

# Anomaly detection (statistical, produces FLAGS not rejections).
# Modified z-score (Iglewicz & Hoaglin) on log values, per category, against
# the *historical* baseline. 3.5 is the commonly cited cut-off.
ANOMALY_Z_THRESHOLD = 3.5
QUANTITY_FLAG_FACTOR = 2.0  # flag quantity > factor * historical p99.5 for that category

# --------------------------------------------------------------------------
# Record signing keys (HMAC-SHA256)
# --------------------------------------------------------------------------
# DEMO ONLY. In production each source would hold its own secret in a key
# vault / HSM and the pipeline would fetch verification keys from there.
# Here a per-source key is derived from a master secret so the demo is
# reproducible. The master can be overridden with an environment variable.
_DEMO_MASTER_KEY = os.environ.get(
    "SDF_DEMO_MASTER_KEY", "securedataflow-dsa4030-demo-master-key-not-for-production"
).encode()


def source_key(source_id: str) -> bytes | None:
    """Return the HMAC key registered for *source_id*, or None if the source is unknown."""
    if source_id not in ALLOWED_SOURCES:
        return None
    return hmac.new(_DEMO_MASTER_KEY, source_id.encode(), hashlib.sha256).digest()


# Seeds make every run reproducible (same dataset, same attacks, same numbers).
CLEAN_SEED = 4030
HISTORICAL_SEED = 2026
ATTACK_SEED = 1
N_CLEAN_RECORDS = 1000
N_HISTORICAL_RECORDS = 5000
