"""Routing, logging, downstream comparison and end-to-end experiment tests."""

import json

import pandas as pd
import pytest
from conftest import make_record

from config import settings as S
from ingestion.loader import naive_ingest, secure_ingest
from main import impact_attribution
from monitoring.evaluation import evaluate
from monitoring.security_log import summarise
from processing.routing import route
from processing.summary import downstream_summary, pandas_summary, prepare_summary_input
from security.validator import ACCEPTED, validate_batch


def _write(records, path):
    pd.DataFrame(records, columns=S.FIELDS).to_csv(path, index=False)
    return path


@pytest.fixture
def small_batch(tmp_path, monkeypatch, baseline):
    monkeypatch.setattr(S, "ARCHIVE_DIR", tmp_path / "archive")
    recs = [make_record(),
            make_record(record_id="TXN-2026-000002", quantity="-1", amount="-2500.00"),
            make_record(record_id="TXN-2026-000003", timestamp="yesterday"),
            make_record(record_id="TXN-2026-000004", quantity="150", unit_price="18500.00", amount="2775000.00")]
    recs.append(dict(recs[0]))  # replay
    path = _write(recs, tmp_path / "incoming.csv")
    batch = secure_ingest(path, "unit test")
    results = validate_batch(batch.records, baseline)
    return batch, results, tmp_path


def test_ingestion_records_metadata_and_archive(small_batch):
    batch, _, _ = small_batch
    assert batch.received == 5
    assert batch.archive_verified is True
    assert len(batch.sha256) == 64
    assert batch.ingested_at and batch.run_id
    assert batch.missing_columns == [] and batch.unexpected_columns == []


def test_ingestion_keeps_raw_text(small_batch):
    batch, _, _ = small_batch
    assert batch.records[2]["timestamp"] == "yesterday"
    assert batch.records[0]["unit_price"] == "2500.00"  # not converted to 2500.0


def test_quarantine_is_separated_from_trusted(small_batch):
    batch, results, tmp = small_batch
    info = route(results, batch, trusted_dir=tmp / "trusted", quarantine_dir=tmp / "quarantine")
    trusted = pd.read_csv(tmp / "trusted" / "trusted_transactions.csv")
    quarantine = pd.read_csv(tmp / "quarantine" / "quarantined_records.csv")
    assert info["trusted_count"] + info["quarantine_count"] == batch.received
    assert list(trusted["source_row"]) == [1]
    assert sorted(quarantine["source_row"]) == [2, 3, 4, 5]
    assert set(trusted["source_row"]).isdisjoint(set(quarantine["source_row"]))
    assert quarantine["reasons"].str.len().min() > 0  # every quarantined record has a reason
    assert set(quarantine["status"]) == {"REJECTED", "FLAGGED"}
    lines = (tmp / "quarantine" / "quarantined_records.jsonl").read_text().splitlines()
    assert len(lines) == 4 and all(json.loads(x)["reasons"] for x in lines)


def test_security_summary_counts(small_batch):
    _, results, _ = small_batch
    s = summarise(results)
    assert (s["received"], s["accepted"], s["rejected"], s["flagged"]) == (5, 1, 3, 1)
    assert s["failures_by_reason_code"]["DUPLICATE_REPLAY"] == 1


def test_naive_ingest_silently_coerces(tmp_path):
    recs = [make_record(), make_record(record_id="TXN-2026-000002", amount="12,5OO.00")]
    df = naive_ingest(_write(recs, tmp_path / "x.csv"))
    assert len(df) == 2 and df["amount"].isna().sum() == 1


def test_downstream_summary_values(tmp_path):
    df = pd.DataFrame({"record_id": ["a", "b", "c"], "category": ["X", "X", "Y"], "amount": [10.0, 30.0, 5.0]})
    s = pandas_summary(prepare_summary_input(df, tmp_path / "s.csv"))
    assert s["records"] == 3 and s["total_revenue"] == 45.0 and s["median_amount"] == 10.0
    assert s["by_category"]["X"] == {"revenue": 40.0, "records": 2, "mean_amount": 20.0}


def test_flowfile_summary_matches_pandas(tmp_path, monkeypatch):
    pytest.importorskip("flowfile")
    import processing.summary as summary_mod
    monkeypatch.setattr(summary_mod, "FLOW_DIR", tmp_path / "flows")
    df = pd.DataFrame({"record_id": list("abcd"), "category": ["X", "X", "Y", ""],
                       "amount": [10.5, 30.25, None, 4.0]})
    s = downstream_summary(df, "unit_test_flow", tmp_path, engine="flowfile")
    assert s["engine"] == "flowfile", s["engine"]
    assert s["matches_pandas_crosscheck"] is True
    assert s["total_revenue"] == 44.75 and s["unparseable_amounts"] == 1 and "(blank)" in s["by_category"]


# ---------------------------------------------------------------- end-to-end experiment
@pytest.fixture(scope="module")
def experiment(generated):
    batch_records = pd.read_csv(S.ATTACKED_FILE, dtype=str, keep_default_na=False).to_dict("records")
    results = validate_batch(batch_records, generated["baseline"])
    manifest = pd.read_csv(S.MANIFEST_FILE)
    return results, manifest, evaluate(results, manifest)


def test_clean_file_is_unchanged_by_attack(generated):
    clean = pd.read_csv(S.CLEAN_FILE, dtype=str)
    assert len(clean) == S.N_CLEAN_RECORDS
    from simulation.dataset import generate_records
    regenerated = generate_records(S.N_CLEAN_RECORDS, S.CLEAN_SEED, S.BATCH_WINDOW_START, S.BATCH_WINDOW_END, 2026)
    assert clean.to_dict("records") == regenerated


def test_attack_batch_composition(generated):
    by = generated["attack"]["by_scenario"]
    assert generated["attack"]["total_rows"] == 1045
    assert by["LEGITIMATE"] == 982 and by["S8_PLAUSIBLE_MANIPULATION"] == 10


def test_every_detectable_scenario_is_fully_quarantined(experiment):
    _, _, ev = experiment
    for row in ev["by_scenario"]:
        if row["scenario"] not in ("LEGITIMATE", "S8_PLAUSIBLE_MANIPULATION"):
            assert row["accepted"] == 0, row


def test_extreme_values_are_flagged_not_rejected(experiment):
    _, _, ev = experiment
    s6 = next(r for r in ev["by_scenario"] if r["scenario"] == "S6_EXTREME_VALUES")
    assert s6["flagged"] == s6["records"]


def test_false_positive_rate_is_low(experiment):
    _, _, ev = experiment
    assert ev["totals"]["false_positive_rate_pct"] < 1.0


def test_clean_batch_alone_is_mostly_accepted(generated):
    recs = pd.read_csv(S.CLEAN_FILE, dtype=str, keep_default_na=False).to_dict("records")
    results = validate_batch(recs, generated["baseline"])
    rejected = [r for r in results if r.status == "REJECTED"]
    assert rejected == []  # no hard-rule false positives on genuine data
    assert sum(r.status == ACCEPTED for r in results) >= 990


def test_impact_attribution_reconciles_with_totals(experiment):
    results, manifest, _ = experiment
    attacked = pd.read_csv(S.ATTACKED_FILE, dtype=str, keep_default_na=False)
    clean = pd.read_csv(S.CLEAN_FILE, dtype={"record_id": str})
    true_total = clean["amount"].sum()
    naive_total = pd.to_numeric(attacked["amount"], errors="coerce").sum()
    attr_a = impact_attribution(attacked, manifest, clean, None)
    assert sum(r["revenue_effect"] for r in attr_a) == pytest.approx(naive_total - true_total, abs=0.05)
    accepted = {r.row_number for r in results if r.status == ACCEPTED}
    trusted_total = pd.to_numeric(attacked["amount"], errors="coerce").iloc[[i - 1 for i in accepted]].sum()
    attr_b = impact_attribution(attacked, manifest, clean, accepted)
    assert sum(r["revenue_effect"] for r in attr_b) == pytest.approx(trusted_total - true_total, abs=0.05)


def test_controls_reduce_downstream_error(experiment):
    results, _, _ = experiment
    attacked = pd.read_csv(S.ATTACKED_FILE, dtype=str, keep_default_na=False)
    true_total = pd.read_csv(S.CLEAN_FILE)["amount"].sum()
    naive_total = pd.to_numeric(attacked["amount"], errors="coerce").sum()
    accepted = [r.row_number - 1 for r in results if r.status == ACCEPTED]
    trusted_total = pd.to_numeric(attacked["amount"], errors="coerce").iloc[accepted].sum()
    assert abs(trusted_total - true_total) < 0.1 * abs(naive_total - true_total)
