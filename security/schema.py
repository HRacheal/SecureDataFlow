"""Pydantic model expressing the per-record rules (types, ranges, allowed values,
timestamp format and window, arithmetic consistency).

Each rule raises an error whose message starts with a reason code in square
brackets, e.g. ``[INVALID_TIMESTAMP]``. The validator converts Pydantic's
errors into those codes so every quarantined record carries machine-readable
reasons as well as a human-readable explanation.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from config import settings as S

Category = Literal["Electronics", "Groceries", "Clothing", "Household", "Stationery"]
Currency = Literal["KES"]
assert list(Category.__args__) == S.ALLOWED_CATEGORIES  # keep model and config in sync
assert list(Currency.__args__) == S.ALLOWED_CURRENCIES


class TransactionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    record_id: str = Field(pattern=S.RECORD_ID_PATTERN)
    source_id: str
    timestamp: datetime
    category: Category
    quantity: int = Field(ge=S.QUANTITY_MIN, le=S.QUANTITY_MAX)
    unit_price: float = Field(ge=S.UNIT_PRICE_MIN, le=S.UNIT_PRICE_MAX, allow_inf_nan=False)
    amount: float = Field(gt=0, allow_inf_nan=False)
    currency: Currency
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_id")
    @classmethod
    def _registered_source(cls, v: str) -> str:
        if v not in S.ALLOWED_SOURCES:
            raise ValueError(f"[DISALLOWED_VALUE] source '{v}' is not a registered source")
        return v

    @field_validator("timestamp", mode="before")
    @classmethod
    def _strict_timestamp(cls, v):
        text = str(v)
        if not re.fullmatch(S.TIMESTAMP_PATTERN, text):
            raise ValueError(f"[INVALID_TIMESTAMP] '{text}' is not ISO 8601 UTC (YYYY-MM-DDTHH:MM:SSZ)")
        try:
            ts = datetime.strptime(text, S.TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            raise ValueError(f"[INVALID_TIMESTAMP] '{text}' is not a real calendar date/time") from None
        if not (S.BATCH_WINDOW_START <= ts <= S.BATCH_WINDOW_END):
            raise ValueError(
                f"[TIMESTAMP_OUTSIDE_WINDOW] {text} outside batch window "
                f"{S.BATCH_WINDOW_START:%Y-%m-%d} to {S.BATCH_WINDOW_END:%Y-%m-%d}"
            )
        return ts

    @model_validator(mode="after")
    def _amount_consistent(self):
        expected = self.quantity * self.unit_price
        if not math.isclose(self.amount, expected, abs_tol=S.AMOUNT_TOLERANCE):
            raise ValueError(
                f"[AMOUNT_INCONSISTENT] amount {self.amount:,.2f} != quantity x unit_price {expected:,.2f}"
            )
        return self


# Map Pydantic's built-in error types to our reason codes.
_PYDANTIC_TYPE_TO_CODE = {
    "missing": "MISSING_REQUIRED_FIELD",
    "int_parsing": "INVALID_TYPE",
    "int_from_float": "INVALID_TYPE",
    "float_parsing": "INVALID_TYPE",
    "finite_number": "INVALID_TYPE",
    "string_type": "INVALID_TYPE",
    "greater_than": "OUT_OF_RANGE",
    "greater_than_equal": "OUT_OF_RANGE",
    "less_than_equal": "OUT_OF_RANGE",
    "literal_error": "DISALLOWED_VALUE",
    "string_pattern_mismatch": "INVALID_FORMAT",
    "extra_forbidden": "UNEXPECTED_FIELD",
}


def _is_negative(value) -> bool:
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False


def validate_record(raw: dict) -> tuple[TransactionRecord | None, list[tuple[str, str, str]]]:
    """Validate one raw record (values as text; blank = missing).

    Returns (model or None, [(reason_code, field, message), ...]).
    """
    data = {k: v for k, v in raw.items() if v is not None and str(v).strip() != ""}
    try:
        return TransactionRecord(**data), []
    except ValidationError as exc:
        reasons = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err.get("loc", ())) or "record"
            msg = err.get("msg", "")
            m = re.search(r"\[([A-Z_]+)\]\s*(.*)", msg)
            if m:
                code, msg = m.group(1), m.group(2)
            else:
                code = _PYDANTIC_TYPE_TO_CODE.get(err.get("type", ""), "INVALID_VALUE")
                if code == "OUT_OF_RANGE" and _is_negative(raw.get(field)):
                    code = "NEGATIVE_VALUE"
                if code == "MISSING_REQUIRED_FIELD":
                    msg = f"required field '{field}' is missing or blank"
                else:
                    msg = f"{field}={raw.get(field)!r}: {msg}"
            reasons.append((code, field, msg))
        return None, reasons
