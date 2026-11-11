"""Unit tests for the individual security controls."""

import pytest
from conftest import make_record

from security.integrity import verify_signature
from security.validator import ACCEPTED, FLAGGED, REJECTED, validate_batch


def codes(result):
    return {r.code for r in result.reasons}


def run_one(rec, baseline):
    return validate_batch([rec], baseline)[0]


# ---------------------------------------------------------------- valid data
def test_valid_record_is_accepted(baseline):
    r = run_one(make_record(), baseline)
    assert r.status == ACCEPTED, r.reasons
    assert r.reasons == []


# ---------------------------------------------------------------- required fields
@pytest.mark.parametrize("field", ["record_id", "source_id", "timestamp", "category", "quantity",
                                   "unit_price", "amount", "currency"])
def test_missing_required_field_is_rejected(field, baseline):
    r = run_one(make_record(**{field: ""}), baseline)
    assert r.status == REJECTED
    assert "MISSING_REQUIRED_FIELD" in codes(r)


def test_missing_signature_is_rejected(baseline):
    r = run_one(make_record(signature=""), baseline)
    assert r.status == REJECTED
    assert {"MISSING_REQUIRED_FIELD", "SIGNATURE_INVALID"} <= codes(r)


# ---------------------------------------------------------------- types
@pytest.mark.parametrize("field,value", [("quantity", "three"), ("quantity", "2.5"), ("quantity", "5 units"),
                                         ("unit_price", "N/A"), ("amount", "12,5OO.00"), ("amount", "NaN"),
                                         ("amount", "inf")])
def test_invalid_type_is_rejected(field, value, baseline):
    r = run_one(make_record(**{field: value}), baseline)
    assert r.status == REJECTED
    assert "INVALID_TYPE" in codes(r)


# ---------------------------------------------------------------- ranges / allowed values
@pytest.mark.parametrize("overrides", [{"quantity": "-2", "amount": "-5000.00"},
                                       {"unit_price": "-2500.00", "amount": "-5000.00"}])
def test_negative_values_are_rejected(overrides, baseline):
    r = run_one(make_record(**overrides), baseline)
    assert r.status == REJECTED
    assert "NEGATIVE_VALUE" in codes(r)


def test_quantity_above_maximum_is_rejected(baseline):
    r = run_one(make_record(quantity="5000", amount="12500000.00"), baseline)
    assert r.status == REJECTED and "OUT_OF_RANGE" in codes(r)


@pytest.mark.parametrize("field,value", [("category", "Crypto"), ("currency", "USD"), ("source_id", "SRC-999")])
def test_disallowed_values_are_rejected(field, value, baseline):
    r = run_one(make_record(**{field: value}), baseline)
    assert r.status == REJECTED
    assert "DISALLOWED_VALUE" in codes(r)


def test_malformed_record_id_is_rejected(baseline):
    r = run_one(make_record(record_id="TXN-26-77"), baseline)
    assert r.status == REJECTED and "INVALID_FORMAT" in codes(r)


def test_inconsistent_amount_is_rejected(baseline):
    r = run_one(make_record(amount="50000.00"), baseline)
    assert r.status == REJECTED and "AMOUNT_INCONSISTENT" in codes(r)


# ---------------------------------------------------------------- timestamps
@pytest.mark.parametrize("ts", ["2026-13-45T10:00:00Z", "2026-02-30T10:00:00Z", "31/10/2026 14:00",
                                "yesterday", "2026-10-15 14:22:05"])
def test_invalid_timestamp_is_rejected(ts, baseline):
    r = run_one(make_record(timestamp=ts), baseline)
    assert r.status == REJECTED and "INVALID_TIMESTAMP" in codes(r)


@pytest.mark.parametrize("ts", ["2027-03-15T09:30:00Z", "2025-12-31T23:00:00Z", "2026-09-30T23:59:59Z"])
def test_timestamp_outside_window_is_rejected(ts, baseline):
    r = run_one(make_record(timestamp=ts), baseline)
    assert r.status == REJECTED and "TIMESTAMP_OUTSIDE_WINDOW" in codes(r)


def test_window_boundaries_are_accepted(baseline):
    for ts in ("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z"):
        assert run_one(make_record(timestamp=ts), baseline).status == ACCEPTED


# ---------------------------------------------------------------- duplicates
def test_exact_replay_rejects_only_the_copy(baseline):
    rec = make_record()
    results = validate_batch([rec, dict(rec)], baseline)
    assert results[0].status == ACCEPTED
    assert results[1].status == REJECTED and "DUPLICATE_REPLAY" in codes(results[1])


def test_replayed_record_still_has_valid_signature():
    """Documents WHY a duplicate check is needed: HMAC cannot detect replay."""
    rec = make_record()
    assert verify_signature(dict(rec))[0] is True


def test_id_conflict_rejects_all_versions(baseline):
    a = make_record()
    b = make_record(quantity="3", amount="7500.00")  # same record_id, different content, validly signed
    results = validate_batch([a, b], baseline)
    assert all(r.status == REJECTED and "DUPLICATE_ID_CONFLICT" in codes(r) for r in results)


def test_distinct_ids_are_not_duplicates(baseline):
    results = validate_batch([make_record(), make_record(record_id="TXN-2026-000002")], baseline)
    assert [r.status for r in results] == [ACCEPTED, ACCEPTED]


# ---------------------------------------------------------------- integrity
def test_tampering_after_signing_is_detected(baseline):
    rec = make_record()
    rec["quantity"], rec["amount"] = "4", "10000.00"  # consistent, plausible, but not re-signed
    r = run_one(rec, baseline)
    assert r.status == REJECTED and codes(r) == {"SIGNATURE_INVALID"}


def test_wrong_source_key_is_detected(baseline):
    rec = make_record()
    rec["source_id"] = "SRC-002"  # signature was made with SRC-001's key
    assert "SIGNATURE_INVALID" in codes(run_one(rec, baseline))


# ---------------------------------------------------------------- anomaly detection
def test_extreme_value_is_flagged_not_rejected(baseline):
    r = run_one(make_record(quantity="150", unit_price="18500.00", amount="2775000.00"), baseline)
    assert r.status == FLAGGED
    assert {"ANOMALY_AMOUNT", "ANOMALY_QUANTITY"} <= codes(r)


def test_extreme_unit_price_is_flagged(baseline):
    r = run_one(make_record(category="Clothing", quantity="1", unit_price="480000.00", amount="480000.00"),
                baseline)
    assert r.status == FLAGGED and "ANOMALY_UNIT_PRICE" in codes(r)


def test_typical_value_is_not_flagged(baseline):
    assert run_one(make_record(), baseline).status == ACCEPTED


def test_plausible_manipulation_is_not_detected(baseline):
    """Known limitation: a validly signed 60% price inflation that stays in the normal range passes."""
    r = run_one(make_record(unit_price="4000.00", amount="8000.00"), baseline)
    assert r.status == ACCEPTED


def test_invalid_record_is_not_also_anomaly_scored(baseline):
    r = run_one(make_record(quantity="150", unit_price="18500.00", amount="1.00"), baseline)
    assert r.status == REJECTED
    assert not any(c.startswith("ANOMALY") for c in codes(r))
