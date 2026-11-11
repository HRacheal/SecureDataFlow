"""Measure control effectiveness against the attack manifest (ground truth).

Only possible in a simulation: in production nobody hands you a list of
which records were malicious. The pipeline itself never reads the manifest.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd

from security.validator import ACCEPTED, FLAGGED, REJECTED, RecordResult

SCENARIO_ORDER = [
    "LEGITIMATE", "S1_MISSING_FIELDS", "S2_INVALID_TYPES", "S3_NEGATIVE_VALUES", "S4_DUPLICATE_IDS",
    "S5_INVALID_TIMESTAMPS", "S6_EXTREME_VALUES", "S7_IN_TRANSIT_TAMPERING", "S8_PLAUSIBLE_MANIPULATION",
    "S9_RULE_VIOLATIONS",
]
DATA_CLASS = {  # how the report classifies each scenario
    "LEGITIMATE": "legitimate",
    "S1_MISSING_FIELDS": "invalid", "S2_INVALID_TYPES": "invalid", "S3_NEGATIVE_VALUES": "invalid",
    "S4_DUPLICATE_IDS": "invalid", "S5_INVALID_TIMESTAMPS": "invalid", "S9_RULE_VIOLATIONS": "invalid",
    "S6_EXTREME_VALUES": "suspicious",
    "S7_IN_TRANSIT_TAMPERING": "plausible but manipulated",
    "S8_PLAUSIBLE_MANIPULATION": "plausible but manipulated",
}


def evaluate(results: list[RecordResult], manifest: pd.DataFrame) -> dict:
    man = manifest.set_index("row_number")
    per = defaultdict(lambda: Counter())
    controls = defaultdict(Counter)
    outcome_vs_expected = Counter()
    misses, false_positives = [], []
    for r in results:
        m = man.loc[r.row_number]
        sc = m["scenario"]
        per[sc][r.status] += 1
        per[sc]["total"] += 1
        for c in {x.control for x in r.reasons}:
            controls[sc][c] += 1
        caught = r.status in (REJECTED, FLAGGED)
        exp = m["expected_outcome"]
        if sc == "LEGITIMATE":
            if caught:
                false_positives.append({"row": r.row_number, "record_id": m["record_id"], "status": r.status,
                                        "reasons": "; ".join(x.message for x in r.reasons)})
        elif not caught:
            misses.append({"row": r.row_number, "record_id": m["record_id"], "scenario": sc,
                           "description": m["description"]})
        outcome_vs_expected[(exp, r.status)] += 1

    rows = []
    for sc in SCENARIO_ORDER:
        c = per.get(sc)
        if not c:
            continue
        quarantined = c[REJECTED] + c[FLAGGED]
        rows.append({
            "scenario": sc, "data_class": DATA_CLASS[sc], "records": c["total"],
            "accepted": c[ACCEPTED], "rejected": c[REJECTED], "flagged": c[FLAGGED],
            "quarantined_pct": round(100 * quarantined / c["total"], 1),
            "controls_triggered": ", ".join(f"{k} ({v})" for k, v in controls[sc].most_common()),
        })

    manipulated = sum(per[s]["total"] for s in per if s != "LEGITIMATE")
    manipulated_caught = sum(per[s][REJECTED] + per[s][FLAGGED] for s in per if s != "LEGITIMATE")
    legit = per["LEGITIMATE"]["total"]
    legit_q = per["LEGITIMATE"][REJECTED] + per["LEGITIMATE"][FLAGGED]
    detectable = sum(per[s]["total"] for s in per if s not in ("LEGITIMATE", "S8_PLAUSIBLE_MANIPULATION"))
    detectable_caught = sum(per[s][REJECTED] + per[s][FLAGGED] for s in per
                            if s not in ("LEGITIMATE", "S8_PLAUSIBLE_MANIPULATION"))
    return {
        "by_scenario": rows,
        "totals": {
            "legitimate_records": legit,
            "manipulated_records": manipulated,
            "manipulated_quarantined": manipulated_caught,
            "manipulated_missed": manipulated - manipulated_caught,
            "detection_rate_pct": round(100 * manipulated_caught / manipulated, 1) if manipulated else None,
            "detection_rate_excl_S8_pct": round(100 * detectable_caught / detectable, 1) if detectable else None,
            "legitimate_quarantined": legit_q,
            "false_positive_rate_pct": round(100 * legit_q / legit, 2) if legit else None,
        },
        "missed_records": misses,
        "legitimate_records_quarantined": false_positives,
    }
