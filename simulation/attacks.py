"""Controlled attack simulation (data poisoning / input tampering).

Reads the clean batch (never modified), produces an *attacked* copy of the
incoming batch and a separate ground-truth manifest describing every row.
The ingestion pipeline never reads the manifest - it is used only afterwards
to measure how well the controls worked.

Two attacker positions are modelled:

* "In-transit tamperer" - can edit or inject rows in the batch file but does
  NOT hold any source signing key (e.g. someone with access to a shared drop
  folder or an unprotected transfer channel).
* "Compromised source / insider" - controls a registered source system and
  therefore produces records with VALID signatures. Only content rules can
  catch what this attacker sends.

Scenario catalogue (expected outcome under the implemented controls):

  S1 MISSING_FIELDS        required fields blank                      -> REJECT  (invalid)
  S2 INVALID_TYPES         text where numbers are expected            -> REJECT  (invalid)
  S3 NEGATIVE_VALUES       negative quantity/price/amount ("refunds")  -> REJECT  (invalid)
  S4 DUPLICATE_IDS         replayed records and ID collisions         -> REJECT  (invalid)
  S5 INVALID_TIMESTAMPS    impossible / wrongly formatted / out of window -> REJECT
  S6 EXTREME_VALUES        within hard limits but far outside history -> FLAG    (suspicious)
  S7 IN_TRANSIT_TAMPERING  plausible edits to genuine records, no key -> REJECT  (signature)
  S8 PLAUSIBLE_MANIPULATION inflated but normal-looking, validly signed -> NOT DETECTED (limitation)
  S9 RULE_VIOLATIONS       unknown source/category/currency, bad ID, inconsistent total, over max -> REJECT
"""

from __future__ import annotations

import copy
import random
from datetime import timedelta

from config import settings as S
from security.integrity import sign_record
from simulation.dataset import read_csv_raw, write_csv

MANIFEST_FIELDS = ["row_number", "record_id", "scenario", "attacker", "expected_outcome", "description"]


def _resign(rec: dict) -> dict:
    """Compromised source: signs whatever it sends (only possible for registered sources)."""
    if S.source_key(rec["source_id"]) is not None:
        rec["signature"] = sign_record(rec)
    return rec


def build_attacked_batch(seed: int = S.ATTACK_SEED) -> dict:
    rng = random.Random(seed)
    clean = read_csv_raw(S.CLEAN_FILE)
    n = len(clean)
    rows = [copy.deepcopy(r) for r in clean]                # working copy; clean file untouched
    labels = [("LEGITIMATE", "-", "ACCEPT", "Unmodified legitimate record") for _ in rows]
    injected: list[tuple[float, dict, tuple]] = []           # (sort_key, record, label)
    next_id = [n + 1]

    def new_id() -> str:
        rid = f"TXN-2026-{next_id[0]:06d}"
        next_id[0] += 1
        return rid

    def rand_ts() -> str:
        span = int((S.BATCH_WINDOW_END - S.BATCH_WINDOW_START).total_seconds())
        return (S.BATCH_WINDOW_START + timedelta(seconds=rng.randrange(span))).strftime(S.TIMESTAMP_FORMAT)

    def forged(category, quantity, unit_price, amount=None, source="SRC-005", **overrides) -> dict:
        if amount is None:
            amount = f"{float(quantity) * float(unit_price):.2f}"
        rec = {"record_id": new_id(), "source_id": source, "timestamp": rand_ts(), "category": category,
               "quantity": str(quantity), "unit_price": str(unit_price), "amount": str(amount), "currency": "KES"}
        rec.update(overrides)
        return rec

    def inject(rec, scenario, attacker, expected, desc, after_index=None):
        key = rng.uniform(after_index + 0.5, n) if after_index is not None else rng.uniform(0, n)
        injected.append((key, rec, (scenario, attacker, expected, desc)))

    # Pick disjoint sets of genuine records to replay / tamper / manipulate.
    by_amount = sorted(range(n), key=lambda i: float(clean[i]["amount"]), reverse=True)
    replay_idx = rng.sample(by_amount[:50], 8)
    remaining = [i for i in range(n) if i not in replay_idx]
    rng.shuffle(remaining)
    collide_idx = remaining[:2]
    tamper_idx = remaining[2:10]
    # S8 targets: records priced below their category median so a ~1.6x inflation still looks normal.
    medians = {}
    for c in S.ALLOWED_CATEGORIES:
        prices = sorted(float(r["unit_price"]) for r in clean if r["category"] == c)
        medians[c] = prices[len(prices) // 2]
    manip_idx = [i for i in remaining[10:] if float(clean[i]["unit_price"]) < 0.8 * medians[clean[i]["category"]]][:10]

    # ---- S1 Missing required fields (compromised source, signed) -------------
    for field, desc in [("source_id", "source_id blank"), ("timestamp", "timestamp blank"),
                        ("category", "category blank"), ("quantity", "quantity blank"),
                        ("amount", "amount blank"), ("signature", "signature stripped")]:
        rec = forged("Household", 2, "2400.00")
        rec[field] = ""
        if field != "signature":
            _resign(rec)
        else:
            rec["signature"] = ""
        inject(rec, "S1_MISSING_FIELDS", "compromised source", "REJECT", desc)

    # ---- S2 Invalid data types ----------------------------------------------
    for q, p, a, desc in [("three", "1500.00", "4500.00", "quantity written as a word"),
                          ("2.5", "1800.00", "4500.00", "fractional quantity"),
                          ("5 units", "350.00", "1750.00", "quantity with unit text"),
                          ("2", "N/A", "3000.00", "unit_price not a number"),
                          ("4", "3125.00", "12,5OO.00", "amount with letter O and comma"),
                          ("3", "2200.00", "NaN", "amount 'NaN'")]:
        rec = _resign(forged("Clothing", q, p, a))
        inject(rec, "S2_INVALID_TYPES", "compromised source", "REJECT", desc)

    # ---- S3 Negative values (disguised refunds / reversals) ---------------------
    for cat, q, p, desc in [("Electronics", "-2", "45000.00", "negative quantity (fake reversal)"),
                            ("Electronics", "-3", "38000.00", "negative quantity (fake reversal)"),
                            ("Household", "1", "-12500.00", "negative unit price"),
                            ("Clothing", "-4", "2600.00", "negative quantity"),
                            ("Electronics", "-1", "61000.00", "negative quantity (fake reversal)"),
                            ("Groceries", "-10", "450.00", "negative quantity")]:
        rec = _resign(forged(cat, q, p))
        inject(rec, "S3_NEGATIVE_VALUES", "compromised source", "REJECT", desc)

    # ---- S4 Duplicate identifiers ------------------------------------------------
    for i in replay_idx:  # exact replay of genuine high-value records (signature is still valid!)
        inject(copy.deepcopy(clean[i]), "S4_DUPLICATE_IDS", "in-transit (replay)", "REJECT",
               f"exact replay of {clean[i]['record_id']}", after_index=i)
    for i in collide_idx:  # different content re-using a genuine ID, validly signed by compromised source
        rec = copy.deepcopy(clean[i])
        rec.update(source_id="SRC-005", category="Electronics", quantity="2", unit_price="29500.00",
                   amount="59000.00")
        inject(_resign(rec), "S4_DUPLICATE_IDS", "compromised source", "REJECT",
               f"ID collision: new content re-uses {clean[i]['record_id']}", after_index=i)

    # ---- S5 Invalid timestamps -----------------------------------------------
    for ts, desc in [("2026-13-45T10:00:00Z", "impossible date (month 13, day 45)"),
                     ("31/10/2026 14:00", "wrong format (DD/MM/YYYY)"),
                     ("yesterday", "free text"),
                     ("2026-10-15 14:22:05", "missing ISO 'T' separator and 'Z' zone"),
                     ("2027-03-15T09:30:00Z", "future date outside batch window"),
                     ("2025-12-31T23:00:00Z", "back-dated outside batch window")]:
        rec = _resign(forged("Household", 3, "2750.00", timestamp=ts))
        inject(rec, "S5_INVALID_TIMESTAMPS", "compromised source", "REJECT", desc)

    # ---- S6 Extreme values (pass hard limits, validly signed) -------------------
    for cat, q, p, desc in [("Electronics", 12, "285000.00", "12 units at 285,000 each"),
                            ("Household", 150, "18500.00", "150 units at 18,500 each"),
                            ("Groceries", 400, "2450.00", "400 grocery units at 2,450 each"),
                            ("Stationery", 600, "950.00", "600 stationery units at 950 each"),
                            ("Clothing", 1, "480000.00", "one clothing item at 480,000")]:
        rec = _resign(forged(cat, q, p))
        inject(rec, "S6_EXTREME_VALUES", "compromised source", "FLAG", desc)

    # ---- S7 In-transit tampering of genuine records (attacker has no key) -------
    for k, i in enumerate(tamper_idx):
        r = rows[i]
        old = (r["quantity"], r["amount"])
        if k % 2 == 0:  # inflate quantity, keep arithmetic consistent so it looks plausible
            q = int(r["quantity"]) + 2
            r["quantity"] = str(q)
            r["amount"] = f"{q * float(r['unit_price']):.2f}"
        else:           # raise price by 40%
            p = round(float(r["unit_price"]) * 1.4, 2)
            r["unit_price"] = f"{p:.2f}"
            r["amount"] = f"{int(r['quantity']) * p:.2f}"
        labels[i] = ("S7_IN_TRANSIT_TAMPERING", "in-transit (no key)", "REJECT",
                     f"genuine record edited after signing: qty/amount {old} -> {(r['quantity'], r['amount'])}")

    # ---- S8 Plausible manipulation by compromised source (re-signed) -----------
    for i in manip_idx:
        r = rows[i]
        old_amt = r["amount"]
        p = round(float(r["unit_price"]) * 1.6, 2)
        r["unit_price"] = f"{p:.2f}"
        r["amount"] = f"{int(r['quantity']) * p:.2f}"
        _resign(r)
        labels[i] = ("S8_PLAUSIBLE_MANIPULATION", "compromised source", "UNDETECTED",
                     f"price inflated 60% but still typical; amount {old_amt} -> {r['amount']}; re-signed")

    # ---- S9 Allowed-value / business-rule violations ----------------------------
    rec = forged("Groceries", 3, "420.00", source="SRC-999")
    rec["signature"] = "0" * 64
    inject(rec, "S9_RULE_VIOLATIONS", "in-transit (no key)", "REJECT", "unregistered source SRC-999")
    inject(_resign(forged("Crypto", 1, "75000.00")), "S9_RULE_VIOLATIONS", "compromised source", "REJECT",
           "category 'Crypto' not allowed")
    inject(_resign(forged("Electronics", 1, "24000.00", currency="USD")), "S9_RULE_VIOLATIONS",
           "compromised source", "REJECT", "currency USD not allowed")
    rec = forged("Household", 2, "3100.00")
    rec["record_id"] = "TXN-26-77"
    inject(_resign(rec), "S9_RULE_VIOLATIONS", "compromised source", "REJECT", "malformed record_id")
    inject(_resign(forged("Clothing", 2, "1500.00", amount="30000.00")), "S9_RULE_VIOLATIONS",
           "compromised source", "REJECT", "amount (30,000) != quantity x unit_price (3,000)")
    inject(_resign(forged("Stationery", 5000, "120.00")), "S9_RULE_VIOLATIONS", "compromised source",
           "REJECT", "quantity 5,000 above hard maximum 1,000")

    # Signatures for S1-S6/S9 forged records that were not signed above.
    for _, rec, _ in injected:
        rec.setdefault("signature", "")

    # Merge genuine rows (keys 0..n-1) with injected rows (random keys) to form the arrival order.
    merged = [(float(i), rows[i], labels[i]) for i in range(n)] + injected
    merged.sort(key=lambda t: t[0])

    out_rows, manifest = [], []
    for row_no, (_, rec, (scenario, attacker, expected, desc)) in enumerate(merged, start=1):
        out_rows.append({f: rec.get(f, "") for f in S.FIELDS})
        manifest.append({"row_number": row_no, "record_id": rec.get("record_id", ""), "scenario": scenario,
                         "attacker": attacker, "expected_outcome": expected, "description": desc})

    write_csv(out_rows, S.ATTACKED_FILE)
    write_csv(manifest, S.MANIFEST_FILE, MANIFEST_FIELDS)
    counts: dict[str, int] = {}
    for m in manifest:
        counts[m["scenario"]] = counts.get(m["scenario"], 0) + 1
    return {"total_rows": len(out_rows), "clean_rows": n, "by_scenario": counts}


if __name__ == "__main__":
    print(build_attacked_batch())
