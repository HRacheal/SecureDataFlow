"""Integrity mechanisms.

1. Per-record HMAC-SHA256 signature
   Each source signs the canonical text of a record with its secret key.
   On ingestion the signature is recomputed and compared.

   What it DETECTS: any change to a signed field made by someone who does
   not hold the source's key (e.g. tampering in transit, edits to a file in a
   shared drop folder), and records injected by a party without a key.

   What it does NOT detect:
   - a compromised source / stolen key (the attacker can sign anything),
   - data that was already wrong before it was signed,
   - replay of a genuinely signed record (the copy has a valid signature;
     this is why a separate duplicate check exists),
   - deletion of whole records (needs a signed batch manifest; not implemented).

2. SHA-256 file fingerprint
   The ingested file is hashed and the hash is written to the run log, and an
   archive copy is kept. Re-hashing the archive later shows whether that copy
   changed *after* ingestion. A bare hash does NOT prove who produced the file
   or that it was not altered before we received it: anybody who changes the
   file can also compute a new hash. It is evidence-preservation, not
   authentication.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Mapping

from config.settings import SIGNED_FIELDS, source_key


def canonical_string(record: Mapping[str, object]) -> str:
    """Join the signed fields (as raw text) in a fixed order with '|'."""
    return "|".join("" if record.get(f) is None else str(record.get(f)) for f in SIGNED_FIELDS)


def sign_record(record: Mapping[str, object]) -> str:
    """Return the hex HMAC-SHA256 signature for *record* using its source's key."""
    key = source_key(str(record.get("source_id", "")))
    if key is None:
        raise ValueError(f"Cannot sign: unknown source {record.get('source_id')!r}")
    return hmac.new(key, canonical_string(record).encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(record: Mapping[str, object]) -> tuple[bool, str]:
    """Check a record's signature. Returns (ok, reason_if_not_ok)."""
    sig = str(record.get("signature") or "")
    if not sig:
        return False, "signature missing"
    key = source_key(str(record.get("source_id") or ""))
    if key is None:
        return False, "no verification key for this source"
    expected = hmac.new(key, canonical_string(record).encode("utf-8"), hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, sig):  # constant-time comparison
        return True, ""
    return False, "signature does not match record content"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
