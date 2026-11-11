"""Security validation layer.

Runs every check on every record (it does not stop at the first failure, so
the quarantine shows *all* problems with a record) and assigns one status:

  ACCEPTED - passed every check -> trusted/
  REJECTED - failed at least one hard rule (invalid data)  -> quarantine/
  FLAGGED  - passed hard rules but is statistically abnormal (suspicious,
             NOT proven malicious) -> quarantine/ for human review

Checks, in order:
  1. required fields, types, ranges, allowed values, timestamp, arithmetic
     consistency                                        (Pydantic, schema.py)
  2. per-record HMAC signature                           (integrity.py)
  3. duplicate record_id within the batch                (batch-level, pandas)
  4. abnormal values vs. historical baseline             (baseline.py)
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from config import settings as S
from security.baseline import modified_z
from security.integrity import verify_signature
from security.schema import validate_record

ACCEPTED, REJECTED, FLAGGED = "ACCEPTED", "REJECTED", "FLAGGED"

# reason code -> (control family, severity)
REASON_CATALOGUE = {
    "MISSING_REQUIRED_FIELD": ("required_fields", "reject"),
    "INVALID_TYPE": ("data_types", "reject"),
    "NEGATIVE_VALUE": ("ranges_allowed_values", "reject"),
    "OUT_OF_RANGE": ("ranges_allowed_values", "reject"),
    "DISALLOWED_VALUE": ("ranges_allowed_values", "reject"),
    "INVALID_FORMAT": ("ranges_allowed_values", "reject"),
    "UNEXPECTED_FIELD": ("ranges_allowed_values", "reject"),
    "INVALID_VALUE": ("ranges_allowed_values", "reject"),
    "INVALID_TIMESTAMP": ("timestamps", "reject"),
    "TIMESTAMP_OUTSIDE_WINDOW": ("timestamps", "reject"),
    "AMOUNT_INCONSISTENT": ("consistency", "reject"),
    "SIGNATURE_INVALID": ("integrity", "reject"),
    "DUPLICATE_REPLAY": ("duplicates", "reject"),
    "DUPLICATE_ID_CONFLICT": ("duplicates", "reject"),
    "ANOMALY_UNIT_PRICE": ("anomaly_detection", "flag"),
    "ANOMALY_AMOUNT": ("anomaly_detection", "flag"),
    "ANOMALY_QUANTITY": ("anomaly_detection", "flag"),
}


@dataclass
class Reason:
    code: str
    field: str
    message: str

    @property
    def control(self) -> str:
        return REASON_CATALOGUE[self.code][0]

    @property
    def severity(self) -> str:
        return REASON_CATALOGUE[self.code][1]

    def as_dict(self) -> dict:
        return {"code": self.code, "field": self.field, "control": self.control,
                "severity": self.severity, "message": self.message}


@dataclass
class RecordResult:
    row_number: int
    raw: dict
    status: str = ACCEPTED
    reasons: list[Reason] = field(default_factory=list)
    model: object | None = None  # validated TransactionRecord when the schema passed

    def decide(self) -> None:
        if any(r.severity == "reject" for r in self.reasons):
            self.status = REJECTED
        elif self.reasons:
            self.status = FLAGGED
        else:
            self.status = ACCEPTED


def _content_key(raw: dict) -> tuple:
    return tuple(raw.get(f, "") for f in S.FIELDS)


def check_duplicates(results: list[RecordResult]) -> None:
    """Exact repeats: keep the first copy, reject the rest (replay).
    Same ID with different content: reject ALL copies, because the pipeline
    cannot tell which version is genuine."""
    groups: dict[str, list[RecordResult]] = defaultdict(list)
    for r in results:
        rid = (r.raw.get("record_id") or "").strip()
        if rid:
            groups[rid].append(r)
    for rid, members in groups.items():
        if len(members) < 2:
            continue
        rows = [m.row_number for m in members]
        if len({_content_key(m.raw) for m in members}) == 1:
            for m in members[1:]:
                m.reasons.append(Reason("DUPLICATE_REPLAY", "record_id",
                                        f"{rid} is an exact repeat of row {members[0].row_number} (rows {rows})"))
        else:
            for m in members:
                m.reasons.append(Reason("DUPLICATE_ID_CONFLICT", "record_id",
                                        f"{rid} appears in rows {rows} with different content; "
                                        f"genuine version cannot be determined"))


def check_anomalies(result: RecordResult, baseline: dict) -> None:
    rec = result.model
    prof = baseline["categories"].get(rec.category)
    if prof is None:
        return
    zp = modified_z(math.log(rec.unit_price), prof["log_price_median"], prof["log_price_mad"])
    za = modified_z(math.log(rec.amount), prof["log_amount_median"], prof["log_amount_mad"])
    t = S.ANOMALY_Z_THRESHOLD
    if abs(zp) > t:
        result.reasons.append(Reason("ANOMALY_UNIT_PRICE", "unit_price",
                                     f"unit_price {rec.unit_price:,.2f} has robust z={zp:+.2f} vs {rec.category} "
                                     f"history (median {prof['price_median_kes']:,.2f}); |z|>{t}"))
    if abs(za) > t:
        result.reasons.append(Reason("ANOMALY_AMOUNT", "amount",
                                     f"amount {rec.amount:,.2f} has robust z={za:+.2f} vs {rec.category} "
                                     f"history (median {prof['amount_median_kes']:,.2f}); |z|>{t}"))
    qlimit = S.QUANTITY_FLAG_FACTOR * prof["quantity_p995"]
    if rec.quantity > qlimit:
        result.reasons.append(Reason("ANOMALY_QUANTITY", "quantity",
                                     f"quantity {rec.quantity} > {S.QUANTITY_FLAG_FACTOR:g} x historical "
                                     f"p99.5 ({prof['quantity_p995']:g}) for {rec.category}"))


def validate_batch(raw_records: list[dict], baseline: dict) -> list[RecordResult]:
    results: list[RecordResult] = []
    for i, raw in enumerate(raw_records, start=1):
        res = RecordResult(row_number=i, raw=raw)
        model, schema_errors = validate_record(raw)
        res.model = model
        res.reasons.extend(Reason(c, f, m) for c, f, m in schema_errors)
        ok, why = verify_signature(raw)
        if not ok:
            res.reasons.append(Reason("SIGNATURE_INVALID", "signature", why))
        results.append(res)

    check_duplicates(results)

    for res in results:
        if res.model is not None and not any(r.severity == "reject" for r in res.reasons):
            check_anomalies(res, baseline)
        res.decide()
    return results
