"""Downstream summary - a simple "October revenue report".

The same calculation is run on (a) the attacked batch loaded without
controls and (b) the trusted output of the secure pipeline, so the effect of
the controls on a business result can be measured.

Engine: Flowfile (flowfile_frame API -> Read -> Group By -> Sort nodes).
Every run saves the Flowfile graph as YAML under reports/flowfile/ so it can
be opened in the Flowfile visual editor. A pandas implementation of the same
summary is kept as an independent cross-check (and as a fallback if
Flowfile cannot be imported).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

from config import settings as S

FLOW_DIR = S.REPORTS_DIR / "flowfile"
_ff = None


def _flowfile():
    """Import Flowfile lazily and quietly (it is slow to import and logs a lot)."""
    global _ff
    if _ff is None:
        os.environ.setdefault("FLOWFILE_TELEMETRY", "0")  # no usage telemetry from the demo
        import flowfile as ff
        _ff = ff
    _quiet_console_handlers()
    return _ff


def _quiet_console_handlers() -> None:
    """Flowfile attaches INFO-level console handlers that would flood the demo output.
    Raise only *console* handlers to WARNING; Flowfile's own file logs are untouched."""
    loggers = [logging.getLogger()] + [lg for lg in logging.root.manager.loggerDict.values()
                                       if isinstance(lg, logging.Logger)]
    for lg in loggers:
        if lg.name.startswith("securedataflow"):
            continue
        for h in lg.handlers:
            if type(h) is logging.StreamHandler:
                h.setLevel(logging.WARNING)


def prepare_summary_input(df: pd.DataFrame, path: Path) -> Path:
    """Write the columns the report needs. Blank categories are labelled so they stay visible."""
    out = pd.DataFrame({
        "record_id": df["record_id"],
        "category": df["category"].fillna("(blank)").replace("", "(blank)"),
        "amount": pd.to_numeric(df["amount"], errors="coerce"),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    return path


def flowfile_summary(csv_path: Path, flow_name: str) -> dict:
    logging.disable(logging.INFO)  # silence Flowfile INFO chatter during the call only
    try:
        return _flowfile_summary(csv_path, flow_name)
    finally:
        logging.disable(logging.NOTSET)


def _flowfile_summary(csv_path: Path, flow_name: str) -> dict:
    ff = _flowfile()
    data = ff.read_csv(str(csv_path), description=f"Read {csv_path.name}")
    by_cat = (data.group_by("category", description="Revenue by category")
              .agg([ff.col("amount").sum().alias("revenue"),
                    ff.col("record_id").count().alias("records"),
                    ff.col("amount").mean().alias("mean_amount")])
              .sort("category", description="Sort by category"))
    overall = data.select([ff.col("record_id").count().alias("records"),
                           ff.col("amount").sum().alias("total_revenue"),
                           ff.col("amount").mean().alias("mean_amount"),
                           ff.col("amount").median().alias("median_amount"),
                           ff.col("amount").max().alias("max_amount"),
                           ff.col("amount").null_count().alias("unparseable_amounts")],
                          description="Overall totals")
    _quiet_console_handlers()
    cat_df = by_cat.collect().to_pandas()
    tot = overall.collect().to_pandas().iloc[0].to_dict()
    _quiet_console_handlers()
    FLOW_DIR.mkdir(parents=True, exist_ok=True)
    flow_file = FLOW_DIR / f"{flow_name}.yaml"
    try:
        by_cat.save_graph(str(flow_file))
        saved = str(flow_file.relative_to(S.PROJECT_ROOT))
    except Exception as exc:  # saving the graph is evidence, not essential to the result
        saved = f"not saved: {exc}"
    return _package(tot, cat_df, engine="flowfile", flow_file=saved)


def pandas_summary(csv_path: Path) -> dict:
    df = pd.read_csv(csv_path)
    amt = df["amount"]
    tot = {"records": len(df), "total_revenue": amt.sum(), "mean_amount": amt.mean(),
           "median_amount": amt.median(), "max_amount": amt.max(), "unparseable_amounts": int(amt.isna().sum())}
    cat = (df.groupby("category").agg(revenue=("amount", "sum"), records=("record_id", "count"),
                                       mean_amount=("amount", "mean")).reset_index().sort_values("category"))
    return _package(tot, cat, engine="pandas", flow_file=None)


def _package(tot: dict, cat_df: pd.DataFrame, engine: str, flow_file) -> dict:
    r2 = lambda v: None if pd.isna(v) else round(float(v), 2)  # noqa: E731
    return {
        "engine": engine,
        "flow_file": flow_file,
        "records": int(tot["records"]),
        "total_revenue": r2(tot["total_revenue"]),
        "mean_amount": r2(tot["mean_amount"]),
        "median_amount": r2(tot["median_amount"]),
        "max_amount": r2(tot["max_amount"]),
        "unparseable_amounts": int(tot["unparseable_amounts"]),
        "by_category": {row["category"]: {"revenue": r2(row["revenue"]), "records": int(row["records"]),
                                          "mean_amount": r2(row["mean_amount"])}
                        for _, row in cat_df.iterrows()},
    }


def downstream_summary(df: pd.DataFrame, name: str, work_dir: Path, engine: str = "flowfile") -> dict:
    """Run the revenue report on *df*. Returns the summary plus a pandas cross-check flag."""
    csv_path = prepare_summary_input(df, work_dir / f"{name}_summary_input.csv")
    reference = pandas_summary(csv_path)
    if engine == "flowfile":
        try:
            result = flowfile_summary(csv_path, name)
        except Exception as exc:  # fall back so the demonstration still completes
            result = dict(reference, engine=f"pandas (Flowfile failed: {exc})")
    else:
        result = reference
    result["matches_pandas_crosscheck"] = summaries_match(result, reference)
    return result


def summaries_match(a: dict, b: dict, tol: float = 0.01) -> bool:
    keys = ["records", "total_revenue", "mean_amount", "median_amount", "max_amount", "unparseable_amounts"]
    for k in keys:
        x, y = a[k], b[k]
        if (x is None) != (y is None) or (x is not None and abs(x - y) > tol):
            return False
    if set(a["by_category"]) != set(b["by_category"]):
        return False
    return all(abs(a["by_category"][c]["revenue"] - b["by_category"][c]["revenue"]) <= tol
               and a["by_category"][c]["records"] == b["by_category"][c]["records"] for c in a["by_category"])
