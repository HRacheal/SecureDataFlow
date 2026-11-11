# SecureDataFlow

**A secure data ingestion and validation system** - DSA 4030 Big Data Security, Group 1: *Securing Data Ingestion Pipelines*.

SecureDataFlow simulates a multi-source ingestion pipeline, injects controlled data-poisoning and tampering attacks into an incoming batch, and shows the effect of those attacks on a downstream revenue report **without** and **with** a validation/security layer. All data is synthetic and fictional.

## Run the demonstration

```powershell
cd C:\Users\Admin\Downloads\SecureDataFlow
.\.venv\Scripts\Activate.ps1
python main.py                 # full experiment (Flowfile computes the downstream report)
python main.py --engine pandas # same experiment, pandas instead of Flowfile (faster start-up)
python -m pytest -v            # 60 automated tests
```

`main.py` takes about 10-20 seconds, mostly Flowfile's import time. Every run regenerates the same data from fixed seeds, so the numbers are reproducible. Console output is also saved to `reports/run_output.txt`.

## What happens in one run

| Stage | What it does | Output |
|---|---|---|
| 0 | Generates 1,000 clean October records plus 5,000 historical records. Builds the anomaly baseline from the history. Injects 9 attack scenarios (63 manipulated rows) into a copy of the batch. | `data/raw/`, `data/reference/`, `data/attacked/` |
| A | Loads the attacked batch with no checks (plain pandas), then runs the revenue report. | console, `reports/experiment_results.json` |
| B | Secure ingestion: records run id, time, source and SHA-256, and archives a copy. Then validates every record (Pydantic rules, HMAC signature, duplicates, anomaly baseline), routes records, logs every failure, and runs the revenue report on trusted records only. | `data/trusted/`, `data/quarantine/`, `logs/` |
| C | Compares A and B with the clean ground truth, attributes the revenue error to each scenario, and scores each control against the attack manifest. | console, `reports/figures/` |

## Project layout

```text
SecureDataFlow/
├── main.py                 runs stages 0, A, B, C
├── config/settings.py      all policy: allowed values, ranges, time window, thresholds, paths, demo keys
├── simulation/             dataset.py (synthetic data)  attacks.py (attack injection + ground-truth manifest)
├── ingestion/loader.py     secure_ingest (metadata, SHA-256, archive, raw text) / naive_ingest
├── security/               schema.py (Pydantic rules)  integrity.py (HMAC, SHA-256)
│                           baseline.py (robust statistics)  validator.py (all checks + decision)
├── processing/             routing.py (trusted / quarantine)  summary.py (Flowfile revenue report)
├── monitoring/             security_log.py  evaluation.py  charts.py
├── tests/                  test_validation.py (controls)  test_pipeline.py (routing, comparison, end-to-end)
├── data/                   raw/ reference/ attacked/ archive/ trusted/ quarantine/
├── logs/                   security_events.jsonl  ingestion_runs.jsonl  pipeline.log
├── reports/                experiment_results.json  run_output.txt  test_results.txt  figures/  flowfile/
├── Flowfile-main/          unmodified Flowfile 0.24.0 source (reference only)
├── SecureDataFlow_DSA4030_Technical_Report.md
└── SecureDataFlow_DSA4030_Presentation.pptx
```

## Record decisions

- **ACCEPTED** records go to `data/trusted/trusted_transactions.csv`.
- **REJECTED** records broke a hard rule (invalid data). They go to `data/quarantine/` with every reason listed.
- **FLAGGED** records passed the hard rules but are statistically abnormal (suspicious, not proven malicious). They also go to quarantine, for human review.

## Flowfile's role

Flowfile 0.24.0 runs the downstream revenue report (Read → Group By → Sort, plus a totals node) through its `flowfile_frame` API. Each run saves the flow to `reports/flowfile/*.yaml`. These flows have been imported into the Flowfile server and executed successfully. The Flowfile results are checked against an independent pandas calculation on every run.

The security controls are implemented in Python with Pydantic and pandas. Flowfile does not provide them. Docker is **not** needed.

## Notes

- The HMAC keys in `config/settings.py` are **demo keys**. A real deployment would use per-source keys from a key vault.
- `data/attacked/attack_manifest.csv` is ground truth for evaluation only. The pipeline never reads it.
