"""SecureDataFlow - DSA 4030 Group 1: Securing Data Ingestion Pipelines.

Runs the complete, reproducible experiment:

  0. generate the synthetic clean batch + historical reference data, build
     the anomaly baseline, and simulate the attacks (clean file untouched)
  A. ingest the attacked batch WITHOUT controls -> downstream revenue report
  B. ingest the same batch WITH controls -> validate -> trusted/quarantine ->
     security logs -> downstream revenue report on trusted records only
  C. compare A and B with the clean ground truth and score the controls
     against the attack manifest

Usage:  python main.py            (from the project folder, with .venv active)
        python main.py --engine pandas   (skip Flowfile, use pandas summary)
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import datetime, timezone

import pandas as pd

from config import settings as S
from ingestion.loader import naive_ingest, secure_ingest
from monitoring import charts
from monitoring.evaluation import SCENARIO_ORDER, evaluate
from monitoring.security_log import summarise, write_logs
from processing.routing import route
from processing.summary import downstream_summary
from security.baseline import build_baseline
from security.validator import ACCEPTED, validate_batch
from simulation.attacks import build_attacked_batch
from simulation.dataset import generate_all

WORK_DIR = S.REPORTS_DIR / "work"
FIG_DIR = S.REPORTS_DIR / "figures"


class Tee(io.TextIOBase):
    """Write console output to the screen and to reports/run_output.txt."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self):
        for st in self.streams:
            st.flush()


def banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def table(rows: list[list], headers: list[str]) -> None:
    cells = [[str(c) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(headers)]
    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(line)
    print("| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |")
    print(line)
    for r in cells:
        print("| " + " | ".join(c.rjust(w) if _num(c) else c.ljust(w) for c, w in zip(r, widths)) + " |")
    print(line)


def _num(s: str) -> bool:
    return s.replace(",", "").replace(".", "").replace("-", "").replace("+", "").replace("%", "").strip().isdigit()


def money(v) -> str:
    return "n/a" if v is None else f"{v:,.2f}"


def pct_dev(v, ref) -> str:
    return "n/a" if v is None or not ref else f"{(v - ref) / ref * 100:+.2f}%"


def impact_attribution(attacked: pd.DataFrame, manifest: pd.DataFrame, clean: pd.DataFrame,
                       accepted_rows: set[int] | None) -> list[dict]:
    """Decompose (reported total - true total) by scenario. accepted_rows=None means 'no controls'."""
    clean_amt = dict(zip(clean["record_id"], clean["amount"].astype(float)))
    amt = pd.to_numeric(attacked["amount"], errors="coerce").fillna(0.0).tolist()
    origin = {"LEGITIMATE", "S7_IN_TRANSIT_TAMPERING", "S8_PLAUSIBLE_MANIPULATION"}
    contrib: dict[str, float] = {}
    counted: dict[str, int] = {}
    for idx, m in manifest.iterrows():
        row_no = int(m["row_number"])
        sc = m["scenario"]
        kept = accepted_rows is None or row_no in accepted_rows
        value = amt[row_no - 1]
        if sc in origin:
            delta = (value - clean_amt[m["record_id"]]) if kept else -clean_amt[m["record_id"]]
        else:
            delta = value if kept else 0.0
        contrib[sc] = contrib.get(sc, 0.0) + delta
        counted[sc] = counted.get(sc, 0) + (1 if kept else 0)
    return [{"scenario": k, "records_counted": counted[k], "revenue_effect": round(v, 2)}
            for k, v in contrib.items()]


def run(engine: str = "flowfile") -> dict:
    t0 = time.time()
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for d in (WORK_DIR, FIG_DIR, S.LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ 0
    banner("STAGE 0 - Synthetic data, baseline and controlled attack simulation")
    gen = generate_all()
    baseline = build_baseline()
    atk = build_attacked_batch()
    clean = pd.read_csv(S.CLEAN_FILE, dtype={"record_id": str})
    manifest = pd.read_csv(S.MANIFEST_FILE)
    print(f"Clean batch (October 2026)       : {gen['clean_records']:>5} records  -> {S.CLEAN_FILE.relative_to(S.PROJECT_ROOT)}")
    print(f"Historical reference (Jul-Sep)   : {gen['historical_records']:>5} records  -> {S.HISTORICAL_FILE.relative_to(S.PROJECT_ROOT)}")
    print(f"Baseline profile                 : {len(baseline['categories'])} categories -> {S.BASELINE_FILE.relative_to(S.PROJECT_ROOT)}")
    print(f"Attacked incoming batch          : {atk['total_rows']:>5} rows     -> {S.ATTACKED_FILE.relative_to(S.PROJECT_ROOT)}")
    print(f"Ground-truth manifest (eval only): {S.MANIFEST_FILE.relative_to(S.PROJECT_ROOT)}")
    table([[k, atk["by_scenario"][k]] for k in SCENARIO_ORDER if k in atk["by_scenario"]],
          ["Scenario in attacked batch", "Rows"])

    truth = downstream_summary(clean, "groundtruth_clean_batch", WORK_DIR, engine)

    # ------------------------------------------------------------------ A
    banner("EXPERIMENT A - Attacked batch ingested WITHOUT security controls")
    naive_df = naive_ingest(S.ATTACKED_FILE)
    exp_a = downstream_summary(naive_df, "experimentA_no_controls", WORK_DIR, engine)
    print(f"Records loaded: {len(naive_df)} (no checks; unparseable numbers silently became NaN: "
          f"{exp_a['unparseable_amounts']} amounts)")
    attr_a = impact_attribution(pd.read_csv(S.ATTACKED_FILE, dtype=str, keep_default_na=False), manifest, clean, None)
    table([[r["scenario"], r["records_counted"], money(r["revenue_effect"])] for r in attr_a if r["scenario"] != "LEGITIMATE"],
          ["Scenario", "Rows counted", "Effect on total revenue (KES)"])

    # ------------------------------------------------------------------ B
    banner("EXPERIMENT B - Same attacked batch ingested WITH security controls")
    batch = secure_ingest(S.ATTACKED_FILE, source_label="October 2026 multi-source batch (simulated)")
    print(f"Run id            : {batch.run_id}")
    print(f"Ingested at (UTC) : {batch.ingested_at}")
    print(f"Source file       : {batch.source_file}")
    print(f"SHA-256           : {batch.sha256}")
    print(f"Archive copy      : {batch.archive_file} (hash re-verified: {batch.archive_verified})")
    print(f"Columns OK        : missing={batch.missing_columns or 'none'} unexpected={batch.unexpected_columns or 'none'}")
    results = validate_batch(batch.records, baseline)
    routing = route(results, batch)
    run_log = write_logs(batch, results, routing)
    summ = summarise(results)
    table([["Received", summ["received"]], ["Accepted -> trusted/", summ["accepted"]],
           ["Rejected (invalid) -> quarantine/", summ["rejected"]],
           ["Flagged (suspicious) -> quarantine/", summ["flagged"]]], ["Security decision", "Records"])
    table([[k, v] for k, v in summ["failures_by_reason_code"].items()], ["Validation failure (reason code)", "Count"])
    trusted_df = pd.read_csv(S.TRUSTED_DIR / "trusted_transactions.csv")
    exp_b = downstream_summary(trusted_df, "experimentB_with_controls", WORK_DIR, engine)
    accepted_rows = {r.row_number for r in results if r.status == ACCEPTED}
    attr_b = impact_attribution(pd.read_csv(S.ATTACKED_FILE, dtype=str, keep_default_na=False), manifest, clean,
                                accepted_rows)

    print("\nSample quarantined records (first of each reason code):")
    seen = set()
    for r in results:
        for x in r.reasons:
            if x.code not in seen and r.status != ACCEPTED:
                seen.add(x.code)
                print(f"  row {r.row_number:>4} {r.raw.get('record_id', ''):<16} {r.status:<8} [{x.code}] {x.message}")

    # ------------------------------------------------------------------ C
    banner("EXPERIMENT C - Comparison of downstream results")
    metrics = [("Records in report", "records"), ("Total revenue (KES)", "total_revenue"),
               ("Mean transaction (KES)", "mean_amount"), ("Median transaction (KES)", "median_amount"),
               ("Largest transaction (KES)", "max_amount"), ("Unparseable amounts", "unparseable_amounts")]
    comp_rows = []
    for label, k in metrics:
        tv, av, bv = truth[k], exp_a[k], exp_b[k]
        fmt = money if isinstance(tv, float) else str
        comp_rows.append([label, fmt(tv), fmt(av), pct_dev(av, tv), fmt(bv), pct_dev(bv, tv)])
    table(comp_rows, ["Metric", "Clean truth", "A: no controls", "A vs truth", "B: with controls", "B vs truth"])
    cats = list(dict.fromkeys(list(truth["by_category"]) + list(exp_a["by_category"])))
    cat_rows = []
    for c in cats:
        tv = truth["by_category"].get(c, {}).get("revenue")
        av = exp_a["by_category"].get(c, {}).get("revenue")
        bv = exp_b["by_category"].get(c, {}).get("revenue")
        cat_rows.append([c, money(tv), money(av), pct_dev(av, tv), money(bv), pct_dev(bv, tv)])
    table(cat_rows, ["Category revenue", "Clean truth", "A: no controls", "A vs truth", "B: with controls", "B vs truth"])
    print("Residual difference with controls, by cause (B total - true total):")
    table([[r["scenario"], r["records_counted"], money(r["revenue_effect"])] for r in attr_b
           if abs(r["revenue_effect"]) > 0.005],
          ["Scenario", "Rows in trusted output", "Effect on total revenue (KES)"])

    ev = evaluate(results, manifest)
    banner("CONTROL EFFECTIVENESS (scored against the attack manifest)")
    table([[r["scenario"], r["data_class"], r["records"], r["accepted"], r["rejected"], r["flagged"],
            f"{r['quarantined_pct']}%"] for r in ev["by_scenario"]],
          ["Scenario", "Class", "Rows", "Accepted", "Rejected", "Flagged", "Quarantined"])
    t = ev["totals"]
    print(f"Legitimate records: {t['legitimate_records']} | Manipulated records: {t['manipulated_records']}")
    print(f"Manipulated records quarantined: {t['manipulated_quarantined']} ({t['detection_rate_pct']}%), "
          f"missed: {t['manipulated_missed']}; excluding the deliberately undetectable S8 set: "
          f"{t['detection_rate_excl_S8_pct']}%")
    print(f"Legitimate records quarantined: {t['legitimate_quarantined']} ({t['false_positive_rate_pct']}%)")
    for fp in ev["legitimate_records_quarantined"]:
        print(f"  legit quarantined: row {fp['row']} {fp['record_id']} {fp['status']}: {fp['reasons']}")
    for ms in ev["missed_records"]:
        print(f"  missed: row {ms['row']} {ms['record_id']} {ms['scenario']}: {ms['description']}")

    print("\nDownstream summary engine:", exp_b["engine"])
    if exp_b["engine"] == "flowfile":
        print("Flowfile results identical to independent pandas calculation:",
              all(x["matches_pandas_crosscheck"] for x in (truth, exp_a, exp_b)))
    for s in (truth, exp_a, exp_b):
        if s.get("flow_file"):
            print("  Flowfile graph saved:", s["flow_file"])

    figs = {
        "total_revenue": charts.total_revenue(truth, exp_a, exp_b, FIG_DIR / "fig1_total_revenue.png"),
        "revenue_by_category": charts.revenue_by_category(truth, exp_a, exp_b, FIG_DIR / "fig2_revenue_by_category.png"),
        "outcomes_by_scenario": charts.outcomes_by_scenario(ev["by_scenario"], FIG_DIR / "fig3_outcomes_by_scenario.png"),
        "failures_by_reason": charts.failures_by_reason(summ["failures_by_reason_code"], FIG_DIR / "fig4_failures_by_reason.png"),
    }

    results_doc = {
        "generated_at": started, "runtime_seconds": None, "engine": engine,
        "data_generation": gen, "attack_simulation": atk, "ingestion": batch.metadata(),
        "security_summary": summ, "routing": routing,
        "downstream": {"clean_ground_truth": truth, "experiment_A_no_controls": exp_a,
                       "experiment_B_with_controls": exp_b},
        "impact_attribution": {"experiment_A": attr_a, "experiment_B": attr_b},
        "evaluation": ev,
        "figures": {k: str(v.relative_to(S.PROJECT_ROOT)) for k, v in figs.items()},
    }
    results_doc["runtime_seconds"] = round(time.time() - t0, 1)
    out = S.REPORTS_DIR / "experiment_results.json"
    out.write_text(json.dumps(results_doc, indent=2, default=str), encoding="utf-8")
    banner(f"DONE in {results_doc['runtime_seconds']} s")
    print("Results  :", out.relative_to(S.PROJECT_ROOT))
    print("Trusted  :", routing["trusted_file"])
    print("Quarantine:", routing["quarantine_file"], "and", routing["quarantine_jsonl"])
    print("Logs     : logs/security_events.jsonl, logs/ingestion_runs.jsonl, logs/pipeline.log")
    print("Figures  :", ", ".join(str(v.relative_to(S.PROJECT_ROOT)) for v in figs.values()))
    return results_doc


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--engine", choices=["flowfile", "pandas"], default="flowfile",
                   help="engine for the downstream summary (default: flowfile)")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    S.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(S.REPORTS_DIR / "run_output.txt", "w", encoding="utf-8") as fh:
        original = sys.stdout
        sys.stdout = Tee(original, fh)
        try:
            print(f"SecureDataFlow experiment run - {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
            run(args.engine)
        finally:
            sys.stdout = original


if __name__ == "__main__":
    main()
