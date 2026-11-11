# SecureDataFlow: Initial Technical Report

**Subject:** Environment preparation and baseline assessment of Flowfile 0.24.0 as the foundation for SecureDataFlow
**Date:** 10 November 2026
**Project location:** `C:\Users\Admin\Downloads\SecureDataFlow`
**Status:** Environment ready. Baseline assessment complete. No SecureDataFlow code written yet.

---

## Evidence Conventions

Every finding in this report is labelled with one of the following tags:

| Label | Meaning |
|---|---|
| **[VERIFIED]** | A command was run, or a live request was made, on 10 Nov 2026 and the result was observed directly. |
| **[INSPECTED]** | Confirmed by reading Flowfile's installed source code or configuration. The behaviour itself was not exercised at runtime. |
| **[RECORDED]** | Done during the earlier setup session and recorded in the project notes. The resulting *state* was re-checked for this report, but the original command output was not re-captured. |
| **[PROPOSED]** | A recommendation or planned functionality. Not implemented. |

---

## 1. Project Overview

SecureDataFlow is a Big Data Security course project. Its aim is a **secure data ingestion and validation platform**: one controlled pipeline through which datasets can be loaded, checked, cleaned, transformed and exported, with security controls applied at each stage.

Intended outcomes **[PROPOSED]**:

- Ingest data from files and external sources through a single controlled pipeline.
- Validate data against defined schemas and quality rules, and reject or quarantine non-conforming records.
- Protect sensitive fields (for example personal data) through masking, pseudonymisation or encryption.
- Enforce authenticated, role-based access to pipelines and outputs.
- Produce a tamper-evident audit trail of who ran what, on which data, with which result.

Flowfile provides the data-processing engine. The security controls will be built by the project team as a separate layer. Flowfile's source code is not modified.

## 2. Flowfile Overview

Flowfile is an open-source (MIT-licensed **[INSPECTED]** `Flowfile-main/LICENSE`) visual ETL (Extract-Transform-Load) tool built on the **Polars** dataframe library. It has three parts:

| Component | Role |
|---|---|
| `flowfile_core` | FastAPI backend: flow graph management, authentication, catalogue, secrets |
| `flowfile_worker` | Compute offloader that executes heavy data operations |
| `flowfile_frame` | Python API that mirrors Polars, so pipelines can be written in code and still render as visual graphs |
| `flowfile` (web) | Pre-built Vue web UI served by the backend |

**[INSPECTED]** `Flowfile-main/pyproject.toml` and package metadata.

### Why Flowfile suits SecureDataFlow

- **Pipelines are graphs of discrete nodes.** Each step (read, filter, formula, write) is an addressable node. Validation and security checkpoints can therefore be inserted between steps and recorded individually.
- **A code API and a visual UI share one model.** Pipelines built in Python with `flowfile_frame` become the same node graph the UI shows. This was **[VERIFIED]** in the functional test in Section 5.3.
- **It is a fast, lazy engine.** Polars builds a query plan and pushes filters down into the scan. This was **[VERIFIED]**: the execution plan printed during the test showed `SELECTION: (col("amount") > 50.0) & col("email").is_not_null()` applied inside the CSV scan.
- **It already includes security building blocks:** JWT authentication, users and groups, and a Fernet-encrypted secrets store (Section 8). These are a starting point, not a complete solution.

## 3. Environment Setup

| Item | Value | Evidence |
|---|---|---|
| Operating system | Windows 11 Pro 10.0.26300 | [VERIFIED] |
| Python (venv) | **3.12.0** (base install `C:\Program Files\Python312`) | [VERIFIED] `python --version` |
| pip | **26.3** (inside the venv) | [VERIFIED] `python -m pip --version` |
| Git | **2.44.0.windows.1** | [VERIFIED] `git --version` |
| Virtual environment | `SecureDataFlow\.venv` | [VERIFIED] |
| Installed packages | 155 packages | [VERIFIED] `pip list` |
| Dependency integrity | `No broken requirements found.` | [VERIFIED] `pip check` |
| Docker CLI | 29.9.2 installed, **engine not running** | [VERIFIED] `docker --version` OK; `docker info` exit code 1 |
| Poetry | Not installed | [VERIFIED] `Get-Command poetry` found nothing |

### Key dependency versions [VERIFIED]

`polars 1.43.2`, `fastapi 0.142.4`, `uvicorn 0.32.1`, `pydantic 2.14.3`, `SQLAlchemy 2.1.8`, `duckdb 1.5.6`, `pyarrow 25.0.1`, `cryptography 48.0.1`, `docker 7.2.0`.

### Version note

`Flowfile-main/.python-version` specifies **3.11**, but the venv uses **3.12.0**. The published package installed and ran correctly on 3.12 (Section 5). The mismatch should be kept in mind if any tests are run against the source tree.

### VS Code configuration [VERIFIED]

`.vscode/settings.json`:

```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
    "python.terminal.activateEnvironment": true
}
```

This makes VS Code use the project venv automatically and activate it in new terminals.

### Git configuration [VERIFIED]

The repository is on branch `main` with **no commits yet**. `.gitignore` excludes `.venv/`, `__pycache__/` and `*.pyc`, and documents how to recreate the venv (`py -3.12 -m venv .venv`).

## 4. Installation

### 4.1 Method [RECORDED, state VERIFIED]

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install Flowfile==0.24.0
```

Current state, confirmed by `pip show flowfile`:

```
Name: Flowfile
Version: 0.24.0
Location: C:\Users\Admin\Downloads\SecureDataFlow\.venv\Lib\site-packages
```

The installation added five console commands to `.venv\Scripts\`: `flowfile.exe`, `flowfile_core.exe`, `flowfile_worker.exe`, `flowfile_scheduler.exe` and `flowfile-migrate.exe`.

### 4.2 Why the published package was chosen over a source install

| Factor | Source (`Flowfile-main/`) | PyPI wheel (`Flowfile==0.24.0`) |
|---|---|---|
| Web UI | **Not built.** `Flowfile-main/flowfile/flowfile/web/static` does not exist **[VERIFIED]**. Building it requires Node.js and the frontend build chain. | **Included.** `site-packages/flowfile/web/static/index.html` exists **[VERIFIED]**. |
| Build tool | Requires **Poetry**, which is not installed **[VERIFIED]** | Plain `pip` |
| Version match | 0.24.0 (`pyproject.toml`) | 0.24.0, the same version |
| Risk to reference source | An editable install (`pip install -e`) ties the environment to the source tree and invites accidental edits | Source tree stays read-only reference material |

Result: the venv runs exactly the same release as the downloaded source, with a working UI, and the source stays untouched.

## 5. Testing

All tests were run on **10 November 2026** against the venv installation.

### 5.1 Launch test [VERIFIED]

Command:

```powershell
.\.venv\Scripts\flowfile.exe run ui --no-browser
```

Startup output (excerpt):

```
INFO:     Uvicorn running on http://127.0.0.1:63578 (Press CTRL+C to quit)
Worker functionality included in unified API
    FlowFile - Visual ETL Tool (Unified Mode)
    Web UI: http://127.0.0.1:63578/ui
    API Docs: http://127.0.0.1:63578/docs
Compute backend 'worker'; worker configured at http://127.0.0.1:63578/worker
Kernel manager warm-up skipped: Error while fetching server API version: (2, 'CreateFile', 'The system cannot find the file specified.')
```

- **Interface URL:** `http://127.0.0.1:63578/ui`
- **API documentation:** `http://127.0.0.1:63578/docs`
- **Bind address:** `127.0.0.1`, so the server is reachable only from this machine.
- **Mode:** Unified. Core and worker run in a single process on one port.

### 5.2 HTTP endpoint checks [VERIFIED]

| Request | Result | Interpretation |
|---|---|---|
| `GET /ui` | **200**, page `<title>Flowfile</title>` | Web UI is served |
| `GET /docs` | **200** | Swagger UI is available |
| `GET /openapi.json` | **200**, 783,821 bytes | **440 API paths**; title "Flowfile Backend" |
| `GET /health` | 404 | Not a valid route. The correct health route is below. |
| `GET /health/status` | **200** | `{"setup_required":false,"master_key_configured":true,"mode":"electron","projects_enabled":true,"projects_confined":false,"git_available":true}` |
| `GET /catalog/namespaces` (no token) | **401 Unauthorized** | Protected endpoints reject anonymous calls |
| `GET /secrets/secrets` (no token) | **401 Unauthorized** | Secrets API is protected |
| `POST /auth/token` (**no credentials**) | **200**, bearer token issued | See Security Gap G1 |
| `GET /catalog/namespaces` (with that token) | **200** | Token grants access |
| `GET /auth/users/me` (with that token) | **200**, `local_user`, `is_admin: true` | The credential-free token is an **administrator** |

The server was stopped after testing and confirmed unreachable afterwards.

### 5.3 Functional pipeline test [VERIFIED]

A synthetic 5-row CSV (`id,name,email,amount,country`, containing one missing email and one malformed email) was processed with the `flowfile_frame` API. The script and its data were kept in the session scratchpad, outside the project.

```python
import flowfile as ff
df = ff.read_csv("input.csv")
res = (df.filter(ff.col("amount") > 50)
         .filter(ff.col("email").is_not_null())
         .with_columns((ff.col("amount") * 1.2).alias("amount_with_vat"))
         .select(["id", "name", "country", "amount_with_vat"]))
res.write_parquet("output.parquet")
```

Observed results:

```
shape: (3, 4)
│ id │ name  │ country │ amount_with_vat │
│ 1  │ Alice │ UK      │ 144.6           │
│ 3  │ Carol │ UK      │ 300.0           │
│ 5  │ Eve   │ UK      │ 360.0           │
parquet rows: 3
graph nodes: [(1,'read'), (2,'filter'), (3,'filter'), (5,'formula'), (6,'select'), (7,'output')]
Number of records written: 3
```

What this confirms:

- CSV ingestion, row filtering, a derived column, column selection and Parquet output all worked end to end.
- The code API produced a **6-node flow graph**, the same structure the visual editor uses.
- Library import took about 6–7 seconds, a one-off startup cost.

The test also exposed a Windows issue. Printing a result table to a default PowerShell console fails with `UnicodeEncodeError: 'charmap' codec`, because the console uses the cp1252 encoding. Running Python with `-X utf8` resolves it.

### 5.4 Not tested

The following were investigated in source only. They were **not** exercised:

- Database, cloud storage, Kafka, REST API and Google Analytics connectors (no external services were configured).
- Python Script nodes and kernels (these require Docker, which is not running).
- Multi-user ("docker") mode, the scheduler, and the UI's drag-and-drop editor through a browser.
- The encrypted secrets store, beyond confirming that its API requires authentication.

## 6. Project Structure [VERIFIED]

```
SecureDataFlow/
├── .git/                 Git repository (branch main, no commits yet)
├── .gitignore            Excludes .venv/, __pycache__/, *.pyc
├── .vscode/
│   └── settings.json     Points VS Code at .venv's interpreter
├── .venv/                Python 3.12.0 venv with Flowfile 0.24.0 + 155 packages (git-ignored)
├── Flowfile-main/        Flowfile 0.24.0 source (ZIP download), read-only reference
│   ├── flowfile_core/    Backend (FastAPI, auth, catalog, secrets)
│   ├── flowfile_worker/  Compute worker
│   ├── flowfile_frame/   Python pipeline API
│   ├── flowfile_frontend/  Vue UI source (not built)
│   ├── flowfile_scheduler/, flowfile_wasm/, kernel_runtime/, shared/, tools/
│   ├── docs/, tests/, test_utils/, data/
│   ├── docker-compose.yml, Makefile, pyproject.toml, poetry.lock, LICENSE (MIT)
│   └── README.md, ROADMAP.md, CONTRIBUTING.md
└── SecureDataFlow_Initial_Technical_Report.md   (this report)
```

**Integrity of `Flowfile-main/` [VERIFIED].** The folder contains 3,748 files and is not a Git checkout (no `.git`), so it cannot be diffed against upstream. A timestamp check found that no files were written in it more than 5 minutes after extraction (12:50, 10 Nov 2026). This indicates the source is unmodified.

**Runtime data outside the project [VERIFIED].** Flowfile stores its state in `%USERPROFILE%\.flowfile\`:

- `database/flowfile_catalog.db` (SQLite)
- `flows/`, `outputs/`, `uploads/`, `logs/`, `system_logs/`, `cache/`, `temp/`
- `telemetry.yaml`

This location is outside the repository. It matters for the security work (see G5 and G6).

**SecureDataFlow's own code** does not exist yet. It should go in a new top-level folder, for example `securedataflow/`, and not inside `Flowfile-main/` **[PROPOSED]**.

## 7. Flowfile Capabilities

The node catalogue was extracted from `flowfile_core/configs/node_store/nodes.py` **[INSPECTED]**: 51 node types in 7 groups. Nodes marked ✔ were exercised in Section 5.3 **[VERIFIED]**.

### 7.1 Ingestion (input)

| Node | Notes |
|---|---|
| `read` ✔ | Local files: **CSV, JSON, Parquet, Excel, IPC/Arrow, NDJSON, Avro, IPC stream** (`input_schema.py`) |
| `manual_input` | Data entered by hand |
| `database_reader` | Through saved DB connections (drivers in the venv: PostgreSQL, MSSQL, SQLAlchemy, ConnectorX) |
| `cloud_storage_reader` | S3, Azure Blob, GCS. Formats: CSV, Parquet, JSON, Delta |
| `kafka_source` | Kafka topic consumer (`max_messages`, `start_offset`, JSON values) |
| `rest_api_reader` | HTTP with headers, auth, pagination and retries |
| `google_analytics_reader`, `catalog_reader`, `list_files`, `external_source`, `flow_input` | Other sources |

### 7.2 Transformation

`formula` ✔, `select` ✔, `multi_field_formula`, `data_cleansing`, `dynamic_rename`, `record_id`, `sort`, `unique` (deduplication), `text_to_rows`, `sample`, `sql_query`, `polars_code`, `python_script` (requires Docker).
Aggregation: `group_by`, `pivot`, `unpivot`, `window_functions`, `record_count`.
Combination: `join`, `cross_join`, `union`, `fuzzy_match`, `graph_solver`, `explode_hierarchy`, `gate`, `wait_for`, `run_flow`.
Machine learning: `train_model`, `apply_model`, `evaluate_model`, `random_split`.

### 7.3 Filtering

`filter` ✔ supports arbitrary Polars expressions: comparisons, null checks, string matching and boolean combinations. Two filters were chained in the test, and Polars merged them and pushed them into the scan.

Filters **remove** rows. They do not route rejected rows anywhere or record why a row was dropped (see G3).

### 7.4 Output

| Node | Notes |
|---|---|
| `output` ✔ | Local files: **CSV, Parquet, Excel, IPC, NDJSON, Avro** |
| `database_writer` | `append` / `replace` / `fail` |
| `cloud_storage_writer` | Parquet, CSV, JSON, **Delta** (overwrite, append, upsert, update, delete) |
| `catalog_writer` | Flowfile's internal catalogue tables |
| `api_response`, `flow_output`, `explore_data` | Serve a result over the API, pass it to a parent flow, or preview it |

### 7.5 Existing platform-level capabilities [INSPECTED]

- **API:** 440 HTTP endpoints, the largest groups being catalog, AI, editor, kernels and community nodes. [VERIFIED count]
- **Authentication:** OAuth2 password flow with JWT tokens (`flowfile_core/auth/jwt.py`), users, user groups and API consumers.
- **Secrets:** a Fernet-encrypted local store (`flowfile_core/auth/secrets.py`). In Docker mode, the master key comes from a Docker secret or an environment variable.
- **Logging:** per-flow run logs (`/logs/{flow_id}`) and catalogue run history (`/catalog/runs`).

## 8. Security Gaps

The controls below are **not** provided automatically by Flowfile, as it was installed and run here. SecureDataFlow must supply them. Severity reflects the project's security goals.

| ID | Gap | Evidence | Severity |
|---|---|---|---|
| **G1** | **Authentication is effectively disabled in local mode.** The server runs in `"electron"` mode. `POST /auth/token` returns a valid token **with no username or password**, and that token belongs to `local_user` with `is_admin: true`. Any local process or user can obtain full admin access to the API. | **[VERIFIED]** Section 5.2; source `routes/auth.py:33`, `auth/jwt.py:229–231` | High |
| **G2** | **No role-based authorisation in local mode.** Every caller is the same single admin user. Users and groups only apply in multi-user Docker mode. | [INSPECTED] `jwt.py` short-circuits to `local_user` | High |
| **G3** | **No schema or data-quality enforcement.** There are no built-in data contracts, expected-type checks, format validation (email, date, ID patterns), range rules, or quarantine of rejected rows. Invalid rows are either kept or silently filtered out. Format checks have to be written by hand as filter expressions. | [VERIFIED] the test's `is_not_null()` filter accepts the malformed `dan@example`; [INSPECTED] node catalogue | High |
| **G4** | **No sensitive-data protection.** There is no PII detection, masking, tokenisation, pseudonymisation or column-level encryption node. The encrypted store covers *connection credentials*, not dataset contents. | [INSPECTED] node catalogue, `secrets.py` | High |
| **G5** | **Outputs and working data are not encrypted at rest.** Written files (Parquet, CSV and so on), uploads, caches and the SQLite catalogue in `%USERPROFILE%\.flowfile\` are stored in plain form. | [VERIFIED] the test output was a plain Parquet file; [VERIFIED] directory listing | Medium–High |
| **G6** | **Telemetry is on.** `%USERPROFILE%\.flowfile\telemetry.yaml` contains `consent: true`. Anonymous usage telemetry is sent unless `FLOWFILE_TELEMETRY=0` is set. A security-focused platform should make this an explicit decision. | [VERIFIED] file contents | Medium |
| **G7** | **No tamper-evident audit trail.** Run logs exist but are operational logs. Records are not signed or hash-chained and do not tie a specific user identity to a specific dataset version. `/clear-logs` deletes logs. | [INSPECTED] `routes/logs.py` | Medium |
| **G8** | **No file-integrity or provenance checks on ingestion.** Input files are not hashed, signed or checked against an allow-list of sources or types. | [INSPECTED] read-node schema | Medium |
| **G9** | **Transport is plain HTTP.** No TLS is configured. This is acceptable only while the server stays bound to `127.0.0.1`. | [VERIFIED] startup URL `http://127.0.0.1` | Low now; High if exposed |
| **G10** | **Arbitrary code execution nodes.** `polars_code`, `python_script` and `sql_query` let a flow author run arbitrary code. Combined with G1, any local process can run code through the API. | [INSPECTED] node catalogue | Medium |

**Controls that do exist** and can be built on: JWT authentication (real enforcement in Docker mode); `401` on anonymous requests to protected endpoints **[VERIFIED]**; Fernet-encrypted credential storage **[INSPECTED]**; localhost-only binding by default **[VERIFIED]**.

## 9. Limitations

### 9.1 Docker dependency [VERIFIED]

The Docker CLI (29.9.2) is installed, but the Docker Desktop engine is not running (`docker info` returns exit code 1). Flowfile reports this at startup:

```
Kernel manager warm-up skipped: Error while fetching server API version:
(2, 'CreateFile', 'The system cannot find the file specified.')
```

Impact:

- **Not affected:** UI, API, and all built-in Polars-based nodes. The functional test ran without Docker.
- **Unavailable:** `python_script` nodes and the kernel or notebook features, which run user code in Docker containers.
- **Unavailable:** Flowfile's **multi-user "docker" mode** (`Flowfile-main/docker-compose.yml`). This is the mode in which real per-user authentication is enforced (see G1/G2). Enabling it requires Docker Desktop and setting `JWT_SECRET_KEY`, `FLOWFILE_INTERNAL_TOKEN` and a master key.
- **Unavailable:** Flowfile's own test helpers for PostgreSQL, MinIO, Kafka and similar services (`start_postgres`, `start_minio` and so on), which launch Docker containers.

### 9.2 Other warnings and limitations

| Item | Detail | Evidence |
|---|---|---|
| Python version mismatch | The venv uses 3.12.0. The source pins 3.11. Works in practice, but upstream may not officially support 3.12. | [VERIFIED] |
| Windows console encoding | Printing results fails under cp1252. Use `python -X utf8` or set `PYTHONUTF8=1`. | [VERIFIED] |
| PowerShell stderr noise | Uvicorn writes INFO logs to stderr, and PowerShell 5.1 shows them as `NativeCommandError`. This is cosmetic only. | [VERIFIED] |
| No source build | The UI cannot be built from `Flowfile-main` without Node.js and Poetry. Any change to Flowfile itself would require that toolchain. | [VERIFIED] |
| Pinned upstream version | The project depends on Flowfile 0.24.0. Upstream changes (the 440-endpoint API, auth behaviour) may break the SecureDataFlow layer on upgrade, so the version must stay pinned. | [VERIFIED] |
| Large dependency footprint | 155 packages, including cloud SDKs, Kafka, LiteLLM (AI features) and ML libraries. This is a wide attack and supply-chain surface for a security project. | [VERIFIED] count |
| Startup cost | `import flowfile` takes about 6–7 s. | [VERIFIED] |
| Unexercised connectors | DB, cloud, Kafka and REST capabilities are documented from source only (Section 5.4). | — |

## 10. Next Development Steps [PROPOSED]

The roadmap is ordered so that every phase produces something testable. SecureDataFlow wraps Flowfile instead of modifying it.

| Phase | Goal | Key tasks | Deliverable / acceptance check |
|---|---|---|---|
| **0. Baseline** (½ day) | Lock in the current state | Make the first Git commit (`.gitignore`, `.vscode`, this report). Generate `requirements.lock` with `pip freeze`. Decide whether to commit `Flowfile-main/` or git-ignore it and re-download it as reference. Set `FLOWFILE_TELEMETRY=0` (G6). | A clean clone plus `pip install -r requirements.lock` reproduces the environment |
| **1. Project skeleton** (1–2 days) | Separate code from Flowfile | Create `securedataflow/` (package), `tests/`, `config/` and `sample_data/` (synthetic only). Add a pytest smoke test that re-runs the Section 5.3 pipeline. | `pytest` passes |
| **2. Validation layer** (1 week) | Close G3 | Declarative schema and rule definitions (YAML or Pydantic) covering types, required fields, regex formats, ranges and allowed values. Split each run into **accepted** and **quarantined** outputs, with a rejection reason per row. Implement with `flowfile_frame` filters and formulas. | Malformed rows (for example `dan@example`) land in quarantine with a reason |
| **3. Sensitive-data protection** (1 week) | Close G4 and G5 | Field classification config. Masking, salted-hash pseudonymisation, and column-level encryption (the `cryptography` library is already installed) applied before output. Encrypt files at rest or write to a protected location. Keys come from environment or OS storage, never from code. | Tests prove protected columns never appear in plaintext in outputs |
| **4. Integrity and audit** (1 week) | Close G7 and G8 | SHA-256 hash of every input and output. An append-only, hash-chained audit log (who, when, flow, input hash, output hash, accepted and rejected counts). An allow-list of input locations and file types. | Altering any audit entry breaks chain verification |
| **5. Access control** (1–2 weeks) | Close G1, G2, G9 and G10 | **Option A:** start Docker Desktop and run Flowfile in Docker mode with strong `JWT_SECRET_KEY`, `FLOWFILE_INTERNAL_TOKEN` and master key, then map users and groups to roles. **Option B:** keep Flowfile private on localhost and put SecureDataFlow's own authenticated API or CLI in front of it with RBAC. Either way, restrict or disable the code-execution nodes and add TLS if the service ever leaves localhost. | An unauthenticated `POST /auth/token` no longer yields admin access to the exposed surface |
| **6. Evaluation and documentation** (1 week) | Demonstrate the security posture | Negative tests (bad schema, injection strings, tampered files, unauthorised calls). Threat model (STRIDE). Final report and demo. | Test suite and report showing each gap G1–G10 as closed, mitigated or accepted |

Decisions needed before Phase 5: **Docker mode (A) or own gateway (B)**. A reuses Flowfile's real authentication but makes Docker a hard dependency. B keeps the deployment simple but means building the access-control layer ourselves.

---

## Appendix A: Commands Executed for This Report (10 Nov 2026)

```powershell
.\.venv\Scripts\python.exe --version            # Python 3.12.0
.\.venv\Scripts\python.exe -m pip --version     # pip 26.3
git --version                                   # 2.44.0.windows.1
.\.venv\Scripts\python.exe -m pip show flowfile # 0.24.0
.\.venv\Scripts\python.exe -m pip check         # No broken requirements found.
.\.venv\Scripts\python.exe -m pip list          # 155 packages
docker --version; docker info                   # 29.9.2; engine unreachable (exit 1)
Get-Command poetry                              # not found
.\.venv\Scripts\flowfile.exe run ui --no-browser   # server on 127.0.0.1:63578
Invoke-WebRequest  /ui, /docs, /openapi.json, /health, /health/status
Invoke-WebRequest  /catalog/namespaces, /secrets/secrets (anonymous -> 401)
Invoke-RestMethod -Method Post /auth/token      # token issued without credentials
Invoke-RestMethod  /auth/users/me               # local_user, is_admin=true
python -I -X utf8 e2e_test.py                   # CSV -> filter -> formula -> select -> Parquet
```

## Appendix B: Source Files Inspected (read-only)

- `.venv/Lib/site-packages/flowfile/__main__.py`: CLI arguments and defaults (port 63578, `--no-browser`)
- `.venv/Lib/site-packages/flowfile_core/configs/node_store/nodes.py`: node catalogue
- `.venv/Lib/site-packages/flowfile_core/schemas/input_schema.py`: supported file formats
- `.venv/Lib/site-packages/flowfile_core/auth/jwt.py`, `auth/secrets.py`, `routes/auth.py`, `routes/logs.py`: authentication, secrets and logging
- `.venv/Lib/site-packages/flowfile_frame/*`: read, scan and write API
- `Flowfile-main/pyproject.toml`, `LICENSE`, `.python-version`
- `%USERPROFILE%\.flowfile\telemetry.yaml`

No file in `Flowfile-main/` or in Flowfile's installed package was modified.
