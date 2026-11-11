"""Statistical baseline built from *historical* (pre-batch) data.

For each category we store the median and the median absolute deviation
(MAD) of log(unit_price) and log(amount), plus the 99.5th percentile of
quantity. Logs are used because prices and amounts are right-skewed;
median/MAD are used instead of mean/standard deviation because they are
robust: a handful of extreme points barely moves them.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings as S


def build_baseline(historical_csv: Path = S.HISTORICAL_FILE, out: Path = S.BASELINE_FILE) -> dict:
    df = pd.read_csv(historical_csv)
    profile: dict = {"source_file": str(historical_csv.relative_to(S.PROJECT_ROOT)), "records": int(len(df)),
                     "categories": {}}
    for cat, g in df.groupby("category"):
        lp = np.log(g["unit_price"].astype(float))
        la = np.log(g["amount"].astype(float))
        profile["categories"][cat] = {
            "n": int(len(g)),
            "log_price_median": float(lp.median()),
            "log_price_mad": float((lp - lp.median()).abs().median()),
            "log_amount_median": float(la.median()),
            "log_amount_mad": float((la - la.median()).abs().median()),
            "quantity_p995": float(g["quantity"].quantile(0.995)),
            "price_median_kes": round(float(math.exp(lp.median())), 2),
            "amount_median_kes": round(float(math.exp(la.median())), 2),
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return profile


def load_baseline(path: Path = S.BASELINE_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def modified_z(value: float, median: float, mad: float) -> float:
    """Iglewicz-Hoaglin modified z-score: 0.6745 * (x - median) / MAD."""
    if mad <= 0:
        return 0.0
    return 0.6745 * (value - median) / mad
