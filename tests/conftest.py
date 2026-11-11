import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings as S  # noqa: E402
from security.integrity import sign_record  # noqa: E402


def make_record(sign: bool = True, **overrides) -> dict:
    """A valid, signed Household record; overrides are applied *before* signing
    (i.e. they model what a legitimate or compromised source sends)."""
    rec = {"record_id": "TXN-2026-000001", "source_id": "SRC-001", "timestamp": "2026-10-10T12:00:00Z",
           "category": "Household", "quantity": "2", "unit_price": "2500.00", "amount": "5000.00",
           "currency": "KES"}
    rec.update({k: v for k, v in overrides.items() if k != "signature"})
    if sign and S.source_key(rec["source_id"]) is not None:
        rec["signature"] = sign_record(rec)
    else:
        rec["signature"] = overrides.get("signature", "")
    if "signature" in overrides:
        rec["signature"] = overrides["signature"]
    return rec


@pytest.fixture(scope="session")
def generated():
    """Generate the (deterministic) datasets, baseline and attacked batch once per test session."""
    from security.baseline import build_baseline
    from simulation.attacks import build_attacked_batch
    from simulation.dataset import generate_all

    generate_all()
    baseline = build_baseline()
    atk = build_attacked_batch()
    return {"baseline": baseline, "attack": atk}


@pytest.fixture
def baseline(generated):
    return generated["baseline"]
