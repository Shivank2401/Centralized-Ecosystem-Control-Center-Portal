# Inventory Data Pipeline — Project Structure & How-To

> **MAINTENANCE RULE**  
> Update **this file** whenever anything changes: folder layout, YAML keys, CLI menus,
> new/edited/removed clients · geos · reports · scripts, output paths, config modules,
> **or portal frontend/backend behaviour**.  
> Keep sections below in sync with the repo — this is the single operator guide.

---

## 1. Stack

| Choice | Decision |
|--------|----------|
| Runtime | **Python CLI** (`run_pipeline.py`) + **Portal** (`portal.py` → FastAPI `backend/` + React `frontend/`) |
| UI | http://127.0.0.1:5173 → API :8000 → `pipeline_engine` → `report_script.*` |
| Orchestration | Same YAML registry (`config_manager/*.yaml`) for CLI and portal |
| Data explorers | Portal **Data** menu: Outputs / Logs / COGS / Pincode under `sanity_data/` |
| Why | Batch ETL over local files + YAML; portal orchestrates without rewriting reports |

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill real paths
python portal.py                 # API :8000
cd frontend && npm run dev       # UI :5173
python run_pipeline.py           # CLI still works
```

---

## 2. Project tree

```
Centralized Ecosystem Portal/
├── .env                          # per-user paths (gitignored) — NEVER commit
├── .env.example                  # template for new machines / users
├── .gitignore
├── requirements.txt
├── run_pipeline.py               # MASTER CLI (interactive + flags)
├── portal.py                     # API launcher: python portal.py (:8000)
│
├── brain/                        # project knowledge base (do not delete)
│   ├── README.md
│   ├── portal.md                 # portal UX / APIs / interactive-run notes
│   ├── common-run-logs.md        # sanity_data/{CLIENT}/logs/*
│   ├── meir-finance.md
│   └── …                         # overview, config, stages, COGS, etc.
│
├── config_manager/               # CONFIGURATION layer
│   ├── project_structure.md      # ← THIS FILE (keep updated)
│   ├── client.yaml
│   ├── geography.yaml
│   ├── report.yaml               # report_stages + reports → Python modules
│   ├── run_sequences.yaml        # saved run sequences (CLI + Portal)
│   ├── paths.py
│   ├── loader.py
│   ├── layouts.py
│   ├── report_helpers.py         # LoadStats, merge, print_script_completed()
│   ├── cogs_local.py
│   ├── esh_sku_cleaning.py / knc_sku_cleaning.py
│   ├── invalid_skus_store.py / invalid_skus.json
│   ├── orders_pincode.py
│   └── __init__.py
│
├── report_script/
│   ├── amazon_reports/     # Stage: common (ESH + KNC); CLIENT_CONFIGS per script
│   │   ├── manage_fba_report.py / reserved_report.py / ageing_report.py / ledger_report.py
│   │   ├── orders_report.py      # 3-month Qty/Sales period table before export
│   │   ├── inventory_database.py
│   │   ├── new_sku_check.py
│   │   └── run_logs.py           # ReportRunLog → sanity_data/{CLIENT}/logs/
│   ├── helper_files_nd_saving/   # Stage: helper files (ex “Supply Chain”); >>> STEP + CLIENT_CONFIGS
│   │   ├── all_helper_files.py / threeG_nd_updike.py  # ESH (CLIENT_CONFIGS); WH standard files
│   │   ├── saving_raw_file_on_date.py  # ESH + KNC dated archives (notebook-style steps)
│   │   ├── download_cogs.py            # ESH + KNC Azure → cogs/{client}/
│   ├── retail/                   # a_kehe / b_sprouts / c_walmart_scintilla + azure_csv_sync (ESH CLIENT_CONFIGS; >>> STEP)
│   ├── finance/                  # a_meir_finance_report.py (ESH CLIENT_CONFIGS; >>> STEP; month fallback)
│   ├── want_to_update/           # esh_cogs / knc_cogs / pincode / invalid_skus
│   ├── utility_codes/            # MySQL import / image names / JSON→CSV
│   ├── atros_code/               # KNC pnl / ads / decomposition
│   ├── requirement_specific/     # vector_report / emami_report / SC_inventory
│   ├── shipping_queue/           # esh_shipping_queue / knc_shipping_queue (CLIENT_CONFIGS; >>> STEP)
│   ├── awd_fees/ / mbr_report/   # packages (register in report.yaml when ready)
│   └── item_master/              # (if present) Azure item-master CRUD
│
├── pipeline_engine/              # shared executor (CLI + portal worker)
│   ├── executor.py               # import_and_run; geo-scoped jobs; progress %; SUCCESS banner
│   ├── registry.py               # YAML load + stage key aliases
│   ├── run_manager.py            # runtime/runs/{id}/ run.json + stdout.log
│   ├── interactive.py            # safe_input / PIPELINE_NON_INTERACTIVE helpers
│   ├── validation.py / ast_validator.py / discovery.py / models.py / logging.py
│
├── backend/                      # FastAPI app (imported by portal.py)
│   ├── main.py
│   ├── api/                      # clients, geos, reports, stages, sequences, runs,
│   │                             # explore (outputs/logs), config_mgmt, report_scripts, …
│   ├── services/                 # config_*, run_service, explore_service, diagnostics, …
│   ├── workers/run_worker.py     # isolated process; tees stdout → runtime/runs/{id}/stdout.log
│   ├── schemas/ / repositories/ / utils/
│
├── frontend/                     # React control center (Vite :5173)
│   └── src/
│       ├── pages/
│       │   ├── Dashboard.tsx / RunPipeline.tsx / ActiveRuns.tsx / RunHistory.tsx
│       │   ├── RunDetail.tsx     # live SSE logs (auto-scroll) + overall progress
│       │   ├── Logs.tsx          # Data → Logs (newest first + last-run datetime)
│       │   ├── Outputs.tsx / CogsPincode.tsx / …
│       │   └── config/           # ConfigOverview, Clients, Geos, Reports (script packages),
│       │                         # Environment, Files, History, Sequences
│       ├── components/layout/Sidebar.tsx
│       ├── hooks/ / services/api.ts / types/
│
├── cogs/                         # local COGS exports {client}/{geo}_{channel}_cogs.parquet
├── pincode/                      # {cc}_amazon_pincode.csv
├── runtime/                      # portal artifacts (gitignored contents)
│   ├── runs/{run_id}/            # run.json + stdout.log (SSE live logs)
│   └── config_backups/           # YAML edit history
├── docs/portal-architecture.md
└── sanity_data/                  # processed outputs (see §6)
    ├── ESH|KNC|EMM/…
    │   ├── manage_fba/ reserved/ ageing/ ledger/ orders/ orders_ASHU/ …
    │   └── logs/{report}/        # latest.log + {YYYYMMDD_HHMMSS}.log
    └── …
```

---

## 3. Data / control flow

```
User (.env paths)
       │
       ▼
CONFIGURATION  (config_manager/*.yaml + paths/loader/layouts)
       │
       ├──────────────────────────────────────┐
       ▼                                      ▼
run_pipeline.py (CLI)                 portal.py → backend + frontend
       │                                      │
       ▼                                      ▼
pipeline_engine.PipelineExecutor ◄──── run_worker (PIPELINE_NON_INTERACTIVE=1)
       │
       ▼
report_script.*.run(client=, geos=)
       │  • geo-scoped reports often invoked once per geo (portal progress)
       │  • print_script_completed() on success
       ▼
STANDARD DATASET  →  sanity_data/{CLIENT}/{report_folder}/
                     + logs/{report}/latest.log
```

Paths are **never** hardcoded to a user OneDrive tree in YAML.  
Each machine sets roots in `.env`; YAML only stores the **env var names**.

---

## 4. CLI (`run_pipeline.py`)

### First run (interactive)

```
========================================
    Data & Development Client Pipeline
========================================

How do you want to run?
1. Run a saved sequence  (none yet — create one first)
2. Create / manage sequences
3. Classic run (clients → geographies → reports)
4. Exit
```

**1 — Run a saved sequence**  
Pick a named sequence from `config_manager/run_sequences.yaml`.

**2 — Create / manage sequences**  
Clients → Geographies → multi-stage report order → save (optionally run now).

**3 — Classic run**

```
Clients:        1 ESH  2 KNC  3 EMM  4 All
Geographies:    1 US … 6 AE  7 All
# comma-separated multi-select works (e.g. 1,2 or ESH,KNC)

Reports:                          ← stage layer (filtered by selected clients)
1. Stage: common
2. Stage: helper_files_nd_saving
...
# then letters a,b,c… / Run All / Go back
```

**Client filter (`clients:` in `report.yaml`):** omit → all clients; list → only when those clients selected.

Accepts `a`, `a,c`, `a-f`, or report name prefixes. Runs selected reports **in sequence order**.

### Flag / one-shot

```bash
python run_pipeline.py --client ESH --geo US,UK --report manage_fba
python run_pipeline.py --client ESH --geo ALL --stage common
python run_pipeline.py --sequence morning_esh_common
```

---

## 5. `config_manager` — what each file does

| File | Role |
|------|------|
| `client.yaml` | Client code, name, `client_id`, `enabled`, `data_root_env`, `cogs_path_env`, `layout`, `geographies` |
| `geography.yaml` | Per client → per geo: COGS sheet, currency, channel, `enabled` |
| `report.yaml` | `report_stages` + reports (`stage`, optional `clients`, `module`, `menu_order`, `output_subdir`) |
| `run_sequences.yaml` | Saved sequences (clients + geos + ordered reports) — CLI + Portal |
| `paths.py` | Resolve `*_DATA_ROOT`, COGS, `SANITY_DATA_ROOT`, retail/revenue/walmart, pincode, … |
| `loader.py` | `get_client()`, `load_geographies()`, `load_reports()`, … |
| `layouts.py` | ESH/KNC folder maps + revenue orders roots |
| `report_helpers.py` | `LoadStats`, parquet load/merge, **`print_script_completed(name)`** success banner |
| `*_sku_cleaning.py` | Client SKU + COGS helpers |
| `orders_pincode.py` | City/state attach from `PINCODE_DATA_DIR` |

### Stage key aliases (`pipeline_engine.registry`)

Report `stage` strings in YAML may not match `report_stages` keys. Aliases:

| Report `stage` value | Resolves to stage key |
|----------------------|------------------------|
| `Common Sanity Reports` / `amazon_reportss` | `common` |
| `Supply Chain` / `supply_chain` | `helper_files_nd_saving` |

Without aliases, portal stage counts show **0 reports** for those packages.

### `.env` keys (see `.env.example`)

| Key | Purpose |
|-----|---------|
| `ESH_DATA_ROOT` / `KNC_DATA_ROOT` / `EMAMI_DATA_ROOT` | Client inventory roots |
| `ESH_COGS_PATH` / `KNC_COGS_PATH` | COGS workbooks |
| `ESH_CENTRAL_ROOT` / `ESH_RETAIL_ROOT` / `ESH_REVENUE_ROOT` / `ESH_WALMART_ROOT` | Retail / revenue / Walmart |
| `AZURE_*` / `CONTAINER_NAME_*` | Optional Azure uploads |
| `SANITY_DATA_ROOT` | Optional override (default repo `sanity_data/`) |
| `PINCODE_DATA_DIR` | Required for Order report |
| `PIPELINE_NON_INTERACTIVE` | Set by portal workers (`1`); scripts must not block on `input()` |
| `MEIR_REPORT_MONTH` | Optional MEIR month override (`Nov-2025`) |

---

## 6. `sanity_data` — where reports save

Default root: `Centralized Ecosystem Portal/sanity_data/`  
(override with `SANITY_DATA_ROOT`)

| Report key | Folder | Files |
|------------|--------|-------|
| `manage_fba` | `{CLIENT}/manage_fba/` | `{GEO}_manage_fba_inventory.parquet` + `.csv` |
| `reserved` | `{CLIENT}/reserved/` | `{GEO}_reserved_inventory.parquet` + `.csv` |
| `ageing` | `{CLIENT}/ageing/` | `{GEO}_ageing_inventory.parquet` + `.csv` |
| `ledger` | `{CLIENT}/ledger/` | `{GEO}_ledger_inventory.parquet` + `.csv` |
| `order` | `{CLIENT}/orders/` | `{GEO}_orders_database.parquet` + `.csv` |
| `order` (ASHU) | `{CLIENT}/orders_ASHU/` | `{GEO}_orders_ASHU.csv` (line-level + `promotion_ids`) |
| `inventory_database` | `{CLIENT}/inventory_database/` | `{GEO}_inventory_database.parquet` + `.csv` |
| `vector_report` | `{CLIENT}/vector_report/` | `{geo}_{platform}_inventory_report.*` |
| `emami_report` | `EMM/…` | Excel + CSV masters (see Emami brain note) |
| `pnl_report` / `ad_sales_report` / `decomposition_chart` | `KNC/pnl|ads|decomposition_chart/` | per-geo + `final_*` |
| retail / Walmart | local Excel/CSV + Azure | see retail scripts |

### Run logs

```
sanity_data/{CLIENT}/logs/{report}/{YYYYMMDD_HHMMSS}.log   # dated snapshot
sanity_data/{CLIENT}/logs/{report}/latest.log              # always newest run
sanity_data/{CLIENT}/logs/new_skus_vs_cogs/{report}/…      # missing SKU CSVs
```

| Report folder | Log contents |
|---------------|--------------|
| manage_fba / reserved / ageing / ledger | Load summary + geo×year + new SKUs vs COGS |
| **orders** | Load summary + geo×year + **Orders period summary table** (GEO × 3 months Qty/Sales) + new SKUs |
| inventory_database | Combined rows + per-geo new SKUs |
| vector | Geo checklists + stock status + new SKUs |

**Orders period summary** (printed immediately before parquet/CSV export):

```
Client- ESH            2026-09              2026-08              2026-07
GEO                  Qty          Sales   Qty          Sales   Qty          Sales
AE                    26         277.80   …
ALL                …
```

Months = current + previous 2 (same early-month rule as before). Helper: `print_orders_three_month_checklist` in `orders_report.py`.

---

## 7. `report_script` — script contract

Every module in `report.yaml` must expose:

```python
def run(*, client: str, geos: list[str] | None = None, **kwargs):
    ...
```

(`main()` alone also works; executor prefers `run`.)

**Module docstring convention** — each script opens with a short purpose plus a **`Covers:`** block (what clients/geos/sources/outputs it handles) and **`Run:`** examples, same style as `helper_files_nd_saving/saving_raw_file_on_date.py`.

On success (no exception):

- **Portal / CLI via executor:** `print_script_completed("<module_stem>", detail="geo=…")`
- **Direct `python script.py`:** same banner from `__main__`

| Folder | Use for |
|--------|---------|
| `amazon_reports/` | Standard Amazon combiners (incl. orders + inventory DB) |
| `helper_files_nd_saving/` | Helper files, 3G/Updike, raw archive (ESH + KNC), COGS download |
| `requirement_specific/` | Built on `sanity_data` (vector, Emami, SC inventory) |
| `want_to_update/` | COGS upload, pincode, invalid SKUs |
| `utility_codes/` | Standalone helpers |
| `retail/` / `finance/` / `atros_code/` | Client-specific packages |

---

## 8. How to change clients / geos / reports

### 8.1 Add a **new client**

| Step | Action |
|------|--------|
| 1 | `client.yaml` + `.env` / `.env.example` |
| 2 | `geography.yaml` |
| 3 | `layouts.py` + SKU cleaner if needed |
| 4 | Wire report `CLIENT_CONFIGS` |
| 5 | Update **this file** |

### 8.2 Add a **geography**

`client.yaml` list + `geography.yaml` + `layouts.py` + `run_pipeline.py` `GEO_OPTIONS` + on-disk folders.

### 8.3 Add a **report**

1. Script under the right `report_script/` package with `run(client=, geos=)`  
2. Register in `report.yaml` (`module`, `stage`, `menu_order`, optional `output_subdir` / `clients`)  
3. Prefer `print_script_completed` only via executor/`__main__` (already wired for known scripts)  
4. Update **this file**

Hide: `enabled: false`. Portal **Developer → Add Report** can also register uploads.

**Common sanity reports** (`amazon_reports/`): each combiner uses `CLIENT_CONFIGS` / overrides — add a new client by registering config (plus yaml/layouts), without changing ETL. Scripts print `>>> STEP` for easier debugging.

**MEIR finance** (`finance/a_meir_finance_report.py`): ESH-only today via `CLIENT_CONFIGS`; same `>>> STEP` style. Ageing / pivot formulas unchanged — new clients need path/layout registration first.

**Helper files** (`helper_files_nd_saving/`): `all_helper_files` + `threeG_nd_updike` are ESH `CLIENT_CONFIGS` (run helpers first); `saving_raw_file_on_date` + `download_cogs` support ESH+KNC. All print `>>> STEP`; ETL unchanged.

**Retail** (`retail/`): KeHE, Sprouts, Walmart Scintilla — ESH `CLIENT_CONFIGS` + `>>> STEP`; shared `azure_csv_sync` for KeHE/Sprouts CSV append. ETL / Azure semantics unchanged.

**Shipping queue** (`shipping_queue/`): separate ESH / KNC scripts with `CLIENT_CONFIGS` + `>>> STEP` + pipeline `run(client=, geos=)`. Clean/discrepancy formulas unchanged.

---

## 9. Portal (frontend + backend)

### Sidebar (current)

| Group | Items |
|-------|--------|
| — | Dashboard |
| **Pipeline** | Run Pipeline · Active Runs · Run History · **Run Sequences** |
| **Configuration** | Overview · Clients · Geographies · **Reports** (script packages) · Paths & Environment · Configuration Files · Configuration History |
| **Developer** | Add Report · Report Registry · Validation · System Diagnostics |
| **Data** | Outputs · **Logs** · COGS · Pincode |

Removed / redirected:

- Top-level **Reports** menu → `/config/reports`
- **Saved Sequences** under Config → use **Pipeline → Run Sequences** (`/config/sequences` redirects)
- **Stages** removed from Configuration sidebar (stage editing still via YAML / registry)

### Configuration → Reports

- `/config/reports` — browse `report_script/` packages (API `GET /api/report-scripts`)
- `/config/reports/:packageName` — scripts + registration status  
- **Browse-only** (no Run from package page — interactive scripts need a terminal / Pipeline)

### Pipeline runs

| Concern | Behaviour |
|---------|-----------|
| Worker | `backend/workers/run_worker.py`; `PIPELINE_NON_INTERACTIVE=1`; stdout → `runtime/runs/{id}/stdout.log` |
| Live UI | `RunDetail.tsx` + SSE `/api/runs/{id}/events` |
| Live logs | Auto-scroll to newest lines (pauses if user scrolls up) |
| Progress | Advances per **geography job** for geo-scoped modules (not only 0→100 at end). Non-geo scripts stay one unit per client×report. |
| Success line | `[SUCCESS] orders_report (geo=AE) completed successfully.` |

Geo-scoped split (executor): default **one invocation per geo**; exceptions that ignore geos stay batched (`threeG_nd_updike`, `all_helper_files`, `SC_inventory`, utility codes, …).

### Data → Logs

| Behaviour | Detail |
|-----------|--------|
| Sort | **Newest last run first** (`latest.log` mtime / `latest_modified`) |
| Datetime | “Last run: …” on each row; each file chip shows its mtime |
| Badge “N saved logs” | Count of files in that folder — usually `latest.log` + dated `{YYYYMMDD_HHMMSS}.log` snapshots (**not** geos or report count) |
| Viewer | Modal; pick dated file or `latest.log` |

API: `GET /api/explore/logs`, `GET /api/explore/logs/content` (`explore_service.list_log_index`).

### Interactive scripts

Scripts that call `input()` must use kwargs / env / `pipeline_engine.interactive.safe_input`.  
MEIR: non-interactive → previous calendar month; override `MEIR_REPORT_MONTH`.

### Config write path

Atomic YAML write → validate → backup under `runtime/config_backups/` → reload registry. Secrets never returned to the browser.

---

## 10. Quick reference — "I want to…"

| Goal | Primary files |
|------|----------------|
| Change machine paths | `.env` only |
| Add client / geo / report | §8 + `report.yaml` / layouts / SKU |
| Run from UI | Portal → Pipeline → Run Pipeline |
| Save a sequence | Portal → Pipeline → Run Sequences **or** CLI menu |
| Browse scripts | Portal → Configuration → Reports |
| See why a run finished | Pipeline → Run Detail (live logs + SUCCESS lines) |
| Find last orders checklist | Data → Logs → ESH / orders (newest first) **or** `sanity_data/ESH/logs/orders/latest.log` |
| Disable report / client | `enabled: false` in YAML **or** Developer → Report Registry |
| Shared helpers / success print | `config_manager/report_helpers.py` |
| Document any change | **this file** + `brain/` as needed |

---

## 11. Related docs

- `brain/README.md` — knowledge base index  
- `brain/portal.md` — portal APIs, stage aliases, Run Detail UX, interactive runs  
- `brain/common-run-logs.md` — log paths and contents  
- `brain/meir-finance.md` — MEIR month behaviour  
- `brain/config.md` / `overview.md` / `pipeline-stages.md`  
- `docs/portal-architecture.md` — phased portal plan  
