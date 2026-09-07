# Inventory Data Pipeline — Project Structure & How-To

> **MAINTENANCE RULE**  
> Update **this file** whenever anything changes: folder layout, YAML keys, CLI menus,
> new/edited/removed clients · geos · reports · scripts, output paths, or config modules.  
> Keep sections below in sync with the repo — this is the single operator guide.

---

## 1. Stack

| Choice | Decision |
|--------|----------|
| Runtime | **Python CLI** (`run_pipeline.py`) + **Portal** (`portal.py` API + `frontend/` React, Phase 6) |
| UI | http://127.0.0.1:5173 → FastAPI :8000 → `pipeline_engine` → existing reports |
| Data explorers | Outputs / Logs under `sanity_data/`; COGS; Pincode (portal Data menu) |
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
│
├── brain/                        # project knowledge base (do not delete)
│   ├── README.md
│   ├── overview.md
│   ├── config.md
│   └── pipeline-stages.md
│
├── config_manager/               # CONFIGURATION layer
│   ├── project_structure.md      # ← THIS FILE (keep updated)
│   ├── client.yaml               # clients + env var *names* + geo list
│   ├── geography.yaml            # per-client geo: COGS sheet, currency, channel
│   ├── report.yaml               # CLI report registry → Python modules
│   ├── run_sequences.yaml        # saved interactive run sequences
│   ├── paths.py                  # resolve paths from .env
│   ├── loader.py                 # YAML → ClientConfig / GeographyConfig
│   ├── layouts.py                # ESH/KNC relative folder layouts under data_root
│   ├── report_helpers.py         # shared LoadStats, merge, to_snake (ex-ecosoul)
│   ├── cogs_local.py             # local cogs/{client}/{geo}_{channel}_cogs reader
│   ├── esh_sku_cleaning.py       # ESH SKU + COGS + Country_helper / warehouse SKU helpers
│   ├── knc_sku_cleaning.py       # KNC SKU + COGS mapping
│   ├── invalid_skus_store.py     # load/save per-client DEFAULT_INVALID_SKUS
│   ├── invalid_skus.json         # ESH / KNC / EMM invalid SKU lists (edited via want_to_update)
│   ├── orders_pincode.py         # pincode → city/state (PINCODE_DATA_DIR)
│   └── __init__.py
│
├── report_script/
│   ├── __init__.py
│   ├── other_scripts/
│   │   └── saving_raw_file_on_date.py    # shared raw archive helper
│   ├── common_sanity_report/             # STANDARD DATASET reports
│   │   ├── manage_fba_report.py
│   │   ├── reserved_report.py
│   │   ├── ageing_report.py
│   │   ├── ledger_report.py
│   │   ├── orders_report.py              # common ESH+KNC Amazon orders (CLI Order)
│   │   ├── inventory_database.py         # manage_fba + reserved + ageing combiner
│   │   ├── inventory_database.ipynb      # original notebook (ESH US reference)
│   │   ├── new_sku_check.py              # shared new-SKU vs COGS checklist
│   │   └── run_logs.py                   # write load/new-SKU/orders summaries to sanity_data/{CLIENT}/logs/
│   ├── supply_chain/                     # ESH helpers + COGS download
│   │   ├── a_all_helper_files.py
│   │   ├── b_3G_nd_updike.py
│   │   ├── c_saving_raw_file_on_date.py  # ESH raw archive (+ fba_inventory ageing)
│   │   └── d_download_cogs.py            # Azure COGS → cogs/{client}/
│   ├── orders/
│   │   ├── esh_orders.py                 # legacy ESH geo notebook dump (reference)
│   │   └── knc_orders.py                 # legacy KNC geo notebook dump (reference)
│   ├── retail/                           # ESH retail scripts
│   │   ├── a_kehe.py                     # KeHE aged / chain / k-solve / inventory → Azure CSV
│   │   ├── b_sprouts.py                  # Sprouts chain / inventory / risk → Azure CSV
│   │   ├── azure_csv_sync.py             # shared Azure CSV append + dedupe upload
│   │   └── c_walmart_scintilla.py        # Walmart Scintilla → Azure parquet (store sales: archive-month CSV append)
│   ├── finance/                          # ESH finance / MEIR closing stock
│   │   ├── a_MEIR_Finance.ipynb          # original MEIR notebook
│   │   └── a_meir_finance_report.py      # parameterized MEIR Closing Stock report
│   ├── want_to_update/                   # drafts / COGS upload / pincode / invalid SKUs
│   │   ├── cogs_io.py                    # shared Azure upload/download + local helpers
│   │   ├── esh_cogs.py                   # ESH sheets → Azure only
│   │   ├── knc_cogs.py                   # KNC sheets → Azure only
│   │   ├── pincode.py                    # pincode.xlsx → pincode/ CSVs
│   │   └── invalid_skus.py               # view/add DEFAULT_INVALID_SKUS → invalid_skus.json
│   ├── utility_codes/                    # standalone utilities (CLI + pipeline stage)
│   │   ├── a_import_any_file_to_mysql.py # CSV/Excel → MySQL (env credentials)
│   │   ├── b_check_duplicate_image.py    # folder image basenames → CSV
│   │   └── c_convert_json_to_csv.py      # flatten JSON → CSV
│   ├── item_master/                      # Azure item-master CRUD (ESH + KNC)
│   │   ├── item_master_manager.py        # menu: import wizard + geo edit sessions
│   │   ├── azure_io.py                   # download / upload / list blobs
│   │   └── schemas.py                    # ESH vs KNC column expectations
│   ├── atros_code/                       # KNC executive PNL / ads / decomposition (UK,DE,AE)
│   │   ├── atros_common.py               # geo paths, SKU helpers, save + Azure upload
│   │   ├── pnl_report.py
│   │   ├── ad_sales_report.py
│   │   └── decomposition_chart.py
│   ├── requirement_specific/             # built on standard dataset
│   │   ├── vector_report.py              # Amazon inventory vector / datahive
│   │   ├── emami_report.py               # Emami UAE requirement report
│   │   ├── emami_uae_code.ipynb          # original Emami notebook (reference)
│   │   └── SC_inventory.py               # ESH inventory supply chain / instock
│
├── cogs/                                 # COGS local exports
│   ├── esh/                              # {country}_{channel}_cogs.parquet
│   └── knc/
├── pincode/                              # {cc}_amazon_pincode.csv
├── pipeline_engine/                      # shared executor (CLI + portal API)
├── backend/                              # FastAPI: config, runs, diagnostics, validate
├── frontend/                             # React control center (Vite)
├── runtime/                              # portal run artifacts (gitignored contents)
├── portal.py                             # API launcher: python portal.py
├── docs/portal-architecture.md           # portal assessment + phased plan
└── sanity_data/                          # processed outputs (see §6)
    ├── ESH/
    │   ├── manage_fba/
    │   ├── reserved/
    │   ├── ageing/
    │   ├── ledger/
    │   ├── orders/
    │   ├── inventory_database/           # {GEO}_inventory_database.parquet
    │   └── vector_report/                # {geo}_{platform}_inventory_report.parquet
    ├── KNC/
    │   ├── pnl/                          # {GEO}_pnl + final_pnl parquet/csv
    │   ├── ads/                          # {GEO}_ads + final_ads
    │   ├── decomposition_chart/          # {GEO}_decomposition_chart + final_*
    │   └── ...
    └── EMM/
        ├── emami_report/                 # Excel summaries (inventory/revenue/marketing/buybox)
        ├── inventory/                    # amazon_inventory.csv, noon_*.csv, …
        ├── ads/
        ├── orders/
        ├── buy_box/
        └── product_pricing/
```
---

## 3. Data / control flow

```
User (.env paths)
       │
       ▼
CONFIGURATION
  client.yaml + geography.yaml + report.yaml
  paths.py / loader.py / layouts.py
  esh_sku_cleaning / knc_sku_cleaning ← invalid_skus.json
       │
       ▼
run_pipeline.py  (Clients → Geographies → Reports)
       │
       ▼
report_script.*.run(client=, geos=)
       │
       ▼
STANDARD DATASET  →  sanity_data/{CLIENT}/{report_folder}/
       │
       ▼ (optional later)
REQUIREMENT REPORTS  (instock, total inventory, city/state orders)
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
Pick a named sequence from `config_manager/run_sequences.yaml` (clients + geos + report order already stored).

**2 — Create / manage sequences**  
1. Clients → Geographies → sequence builder (multi-stage report order)  
2. Save with a name  
3. Optionally run it now; or delete existing sequences  

Shortcuts in the builder: `2-a,b,c` or `1-a-f`, then `D` to finish.

**3 — Classic run** (previous flow):

```
Clients:        1 ESH  2 KNC  3 All
Geographies:    1 US … 6 AE  7 All

Reports:                          ← stage / class layer (filtered by selected clients)
1. Stage: common
2. Stage: supply_chain
...
# then letters a,b,c… / Run All / Go back
```

**Client filter (`clients:` in `report.yaml`):**
- Omit on a stage/report → visible for every selected client
- `clients: [ESH]` → only when ESH is selected
- `clients: [ESH, KNC]` → when either is selected
- At run time, client-specific reports are skipped for non-matching clients

Accepts `a`, `a,c`, `a-f`, or report name prefixes. **Run All** runs every enabled report in that stage. **Go back** returns to the stage list.

Then runs selected reports **in sequence order** and prints **Pipeline finished.**

### After finish — next-action menu

```
Current selection: clients=... | geos=... | sequence(N)=...

What next?
1. Rerun last selection
2. Classic: change reports only (same clients + geos)
3. Classic: change geographies (keep clients)
4. Save current selection as a sequence
5. Back to main menu (saved sequences / create / classic)
6. Exit          (Enter also exits)
```

### Flag / one-shot (no post-run menu)

```bash
python run_pipeline.py
python run_pipeline.py --client ESH --geo US,UK --report manage_fba
python run_pipeline.py --client ESH --geo ALL --stage common
python run_pipeline.py --client ALL --geo ALL --report ledger,ageing
python run_pipeline.py --sequence morning_esh_common
python run_pipeline.py --interactive
```

`--report a,b,c` order is the run sequence. `--sequence <id>` runs a saved entry from `run_sequences.yaml`.  
Selection flow: **mode → (saved | create | classic clients→geos→reports) → run**.

---

## 5. `config_manager` — what each file does

| File | Role |
|------|------|
| `client.yaml` | Client code, name, `client_id`, `enabled`, `data_root_env`, `cogs_path_env`, `layout`, `geographies` list |
| `geography.yaml` | Per client → per geo: `cogs_sheet_name`, `country_currency`, `orders_sales_channel`, `enabled` |
| `report.yaml` | `report_stages` + reports (`stage`, optional `clients`, `label`, `module`, `menu_order`) |
| `run_sequences.yaml` | Saved interactive run sequences (clients + geos + ordered reports) |
| `paths.py` | `ESH_DATA_ROOT`, `KNC_DATA_ROOT`, `EMAMI_DATA_ROOT`, COGS paths; optional `SANITY_DATA_ROOT`, `PINCODE_DATA_DIR`, `ESH_CENTRAL_ROOT`, `ESH_RETAIL_ROOT`, `ESH_REVENUE_ROOT`, `ESH_WALMART_ROOT`, `ESH_COUNTRY_HELPER_PATH`, `ESH_DEMAND_INSTOCK_ROOT` |
| `loader.py` | `get_client()`, `load_clients()`, `load_geographies()`, `load_reports()` |
| `layouts.py` | ESH folder→code map; ESH revenue orders roots; KNC relative paths per report type (`ledger`/`manage_fba`/`reserved`/`ageing`/`orders`) |
| `report_helpers.py` | Shared `LoadStats`, ignore rules, parquet load/merge, `to_snake` / `_clean_col` |
| `*_sku_cleaning.py` | Client SKU + COGS; ESH also warehouse CASE/`custom_split` + `load_country_helper()` |
| `orders_pincode.py` | City/state attach; dir from `PINCODE_DATA_DIR` |

### `.env` keys (see `.env.example`)

| Key | Purpose |
|-----|---------|
| `ESH_DATA_ROOT` | Ecosoul inventory root (`us/`, `canada/`, …) |
| `KNC_DATA_ROOT` | Kinetica client DB root |
| `EMAMI_DATA_ROOT` | Emami UAE root (`input/amazon|noon|noon_minutes/uae/…`) |
| `EMAMI_OUTPUT_ROOT` | Optional Emami local root (default `sanity_data/EMM`) |
| `CONTAINER_NAME_EMAMI` | Emami Azure container (default `thrive-client-emami`) |
| `KNC_DATA_ROOT` | Kinetica DB root (`Inventory/`, `Germany/`, `UAE/`, …) |
| `ESH_COGS_PATH` / `KNC_COGS_PATH` | COGS workbooks |
| `ESH_CENTRAL_ROOT` | Optional; central root for `retail/`, `logistics/` (default: parent of `ESH_DATA_ROOT`) |
| `ESH_RETAIL_ROOT` | Optional; KeHE / Sprouts / retail item-master tree (default: `{ESH_CENTRAL_ROOT}/retail`) |
| `ESH_REVENUE_ROOT` | Optional; revenue tree for Amazon orders (default: `{ESH_CENTRAL_ROOT}/revenue`) |
| `ESH_WALMART_ROOT` | Required for Walmart Scintilla; folder with `sku_helper.csv` / eComm workbooks |
| `AZURE_STORAGE_CONNECTION_STRING` | Optional; Azure uploads (or account name + key) |
| `AZURE_STORAGE_ACCOUNT_NAME` / `AZURE_STORAGE_ACCOUNT_KEY` | Alternative to connection string |
| `CONTAINER_NAME_ESH` | ESH Azure container (e.g. `thrive-client-ecosoulhome`) |
| `ITEM_MASTER_AZURE_CONNECTION_STRING` | Optional; item-master blobs (falls back to shared Azure conn) |
| `ITEM_MASTER_CONTAINER` | Azure container (default `app-helper`) |
| `ITEM_MASTER_BLOB_PREFIX` | Folder inside container (default `item_master`) → `{prefix}/{CLIENT}.parquet` |
| `ESH_COUNTRY_HELPER_PATH` | Optional; Country_helper.xlsx (default under inventory `dashboard_essential_files/`) |
| `ESH_DEMAND_INSTOCK_ROOT` | Optional; Demand_instock helper export root |
| `SANITY_DATA_ROOT` | Optional override (default: repo `sanity_data/`) |
| `PINCODE_DATA_DIR` | Required for Order report; folder with `{us,uk,...}_amazon_pincode.csv` |
| `INVENTORY_BASE` | Optional alias for ESH root (saving_raw script) |

---

## 6. `sanity_data` — where reports save

Default root: `Centralized Ecosystem Portal/sanity_data/`  
(override with `SANITY_DATA_ROOT` in `.env`)

| Report key | Script folder name | Files |
|------------|--------------------|-------|
| `manage_fba` | `{CLIENT}/manage_fba/` | `{GEO}_manage_fba_inventory.parquet` + `.csv` |
| `reserved` | `{CLIENT}/reserved/` | `{GEO}_reserved_inventory.parquet` + `.csv` |
| `ageing` | `{CLIENT}/ageing/` | `{GEO}_ageing_inventory.parquet` + `.csv` |
| `ledger` | `{CLIENT}/ledger/` | `{GEO}_ledger_inventory.parquet` + `.csv` |
| `order` | `{CLIENT}/orders/` | `{GEO}_orders.parquet` + `.csv` |
| `inventory_database` | `{CLIENT}/inventory_database/` | `{GEO}_inventory_database.parquet` + `.csv` |
| `order` (ASHU) | `{CLIENT}/Orders_Ashu/` | `{GEO}_orders_ASHU.csv` (line-level + `promotion_ids`, pre-pivot) |
| `vector_report` | `{CLIENT}/vector_report/` | `{geo}_{platform}_inventory_report.parquet` + `.csv` |
| `emami_report` | `EMM/` | Excel under `EMM/emami_report/`; CSV masters under `EMM/{inventory\|ads\|orders\|buy_box\|product_pricing}/` (Azure upload prompted after save) |
| `pnl_report` | `KNC/pnl/` | `{GEO}_pnl.parquet/.csv` + `final_pnl.parquet/.csv` |
| `ad_sales_report` | `KNC/ads/` | `{GEO}_ads.parquet/.csv` + `final_ads.parquet/.csv` |
| `decomposition_chart` | `KNC/decomposition_chart/` | `{GEO}_decomposition_chart.parquet/.csv` + `final_decomposition_chart.parquet/.csv` |
| `item_master` | `item_master/` | local cache `sanity_data/item_master/{CLIENT}.parquet` (+ `.csv`) |
| `saving_reports` | *(none — not sanity_data)* | Dated CSVs under `{*_DATA_ROOT}/…/YYYY/Mon-YYYY/` |
| `a_kehe` / `b_sprouts` | *(local Excel + Azure CSV)* | Excel under `{ESH_RETAIL_ROOT}/Retail-Dashboard_Files/` (+ dated backup); Azure CSV under `{CONTAINER_NAME_ESH}/sanity_data/retail/` (`kehe_*.csv`, `sprout*.csv`) |
| `walmart_scintilla` | *(local + Azure)* | Local masters under `{ESH_WALMART_ROOT}/sanity_report/walmart_scintilla_*.csv`; Azure parquet under `{CONTAINER_NAME_ESH}/{WALMART_BLOB_PREFIX}/` replaced from local CSV (no daily Azure download). Month archives remain under `{dataset}/{year}/{month}/` |

### Run logs (common / vector summaries)

Each common sanity report (and vector) writes a readable text log so you do not need to scroll terminals:

```
sanity_data/{CLIENT}/logs/{report}/{YYYYMMDD_HHMMSS}.log
sanity_data/{CLIENT}/logs/{report}/latest.log
```

| Report folder | Contents |
|---------------|----------|
| `manage_fba`, `reserved`, `ageing`, `ledger` | Load summary + Geography×Year breakdown + new SKUs vs COGS |
| `orders` | Load summary + geo×year + current/previous month rows\|qty\|sales per geo + new SKUs |
| `inventory_database` | Combined rows + per-geo checklist (new SKUs; stock status is n/a here) |
| `vector` | Full geo checklists including stock status counts + new SKUs |

Missing SKUs (when any geo fails COGS check) also export to
`sanity_data/{CLIENT}/logs/new_skus_vs_cogs/{report}/latest.csv` — one row per SKU.

Helper: `report_script/common_sanity_report/run_logs.py` (`ReportRunLog`, `export_new_skus_csv`).

Example:

```
sanity_data/ESH/manage_fba/US_manage_fba_inventory.parquet
sanity_data/KNC/ledger/UK_ledger_inventory.parquet
sanity_data/KNC/logs/orders/latest.log
```

Each standard report script's `output_dir_for()` builds:

```python
paths.sanity_data_root() / client_code.upper() / "<folder>"
```

`output_subdir` in `report.yaml` is **optional**:
- Standard / requirement reports that write under `sanity_data/` should set it (and match the script folder).
- Utility/archive reports like `saving_reports` omit it — they write dated files into the client's inventory tree (`ESH_DATA_ROOT` / `INVENTORY_BASE`), not `sanity_data/`.

---

## 7. `report_script` — script contract

Every module listed in `report.yaml` must be importable and expose:

```python
def run(*, client: str, geos: list[str] | None = None, **kwargs):
    ...
```

(`main()` alone also works; CLI prefers `run`.)

| Folder | Use for |
|--------|---------|
| `common_sanity_report/` | Standard Amazon inventory combiners (manage FBA, reserved, ageing, ledger, orders, inventory database) |
| `orders/` | Order processing scripts |
| `requirement_specific/` | Reports that consume `sanity_data` (instock, total inventory, …) |
| `want_to_update/` | COGS / pincode / invalid SKUs producers and drafts |
| `utility_codes/` | Standalone helpers (MySQL import, image names, JSON→CSV) |
| `other_scripts/` | Utilities (raw datewise archive, etc.) — not in main report menu unless registered |

---

## 8. How to change clients / geos / reports

### 8.1 Add a **new client** (e.g. `ABC`)

| Step | File / action |
|------|----------------|
| 1 | `client.yaml` — add `ABC:` block (`name`, `client_id`, `enabled`, `data_root_env`, `cogs_path_env`, `layout`, `geographies`) |
| 2 | `.env` + `.env.example` — add `ABC_DATA_ROOT=...` and `ABC_COGS_PATH=...` |
| 3 | `geography.yaml` — add `ABC:` with each geo's COGS sheet / currency / channel |
| 4 | `layouts.py` — if layout is new (not `esh`/`knc`), add folder maps / `KNC_GEO_REL`-style roots |
| 5 | SKU module — add `abc_sku_cleaning.py` (or reuse) and wire in each report's `CLIENT_CONFIGS` / `sku_backend` |
| 6 | Common reports — extend `_abc_config()` (or generic layout) in each `*_report.py` that must support ABC |
| 7 | Update **this file** (§2 tree + §8) |

Disable without deleting: set `enabled: false` in `client.yaml`.

### 8.2 Edit / delete a **client**

| Action | Where |
|--------|--------|
| Rename / change id | `client.yaml` |
| Change data/COGS path | `.env` only (YAML keeps env *names*) |
| Remove from CLI | `enabled: false` **or** delete block from `client.yaml` + geos in `geography.yaml` |
| Remove SKU/layout code | `*_sku_cleaning.py`, `layouts.py`, report `CLIENT_CONFIGS` |

### 8.3 Add a **new geography** for an existing client (e.g. ESH → `IE`)

| Step | File / action |
|------|----------------|
| 1 | `client.yaml` — append `IE` to that client's `geographies:` list |
| 2 | `geography.yaml` — under that client, add `IE:` (`cogs_sheet_name`, currency, channel, `enabled`) |
| 3 | `layouts.py` — ESH: add folder in `ESH_GEO_FOLDERS` (e.g. `"ireland": "IE"`). KNC: add path tuple under each relevant report in `KNC_GEO_REL` |
| 4 | `run_pipeline.py` — add `("IE", "IE")` to `GEO_OPTIONS` if it should appear in the geo menu |
| 5 | SKU sheets map — auto from `geography.yaml` via `layouts.cogs_sheets_for()`; ensure COGS workbook has the sheet |
| 6 | On-disk folders — create inventory folders under that client's `*_DATA_ROOT` |
| 7 | Update **this file** |

Disable a geo: `enabled: false` under that geo in `geography.yaml` (and/or remove from `client.yaml` list).

### 8.4 Add / edit / remove a **report in the CLI menu**

| Step | File / action |
|------|----------------|
| 1 | Write script under the right `report_script/` folder with `run(client=, geos=)` |
| 2 | `report.yaml` → under `reports:` add key, `label`, `stage`, optional `clients: [ESH]` / `[ESH, KNC]`, `module`, `menu_order`, `enabled: true` (+ `output_subdir` only if writing to `sanity_data/`) |
| 3 | If the stage is new — add it under `report_stages:` with `label`, `order`, optional `clients:` |
| 4 | Script `output_dir_for()` → save under `sanity_data/{CLIENT}/<folder>/` (if applicable) |
| 5 | If KNC paths differ — extend `layouts.KNC_GEO_REL` |
| 6 | If client-specific config — add `_esh_config` / `_knc_config` (or shared) in the new script |
| 7 | Update **this file** (§4 CLI + §6 table + tree) |

Hide from menu without deleting: `enabled: false` in `report.yaml`.  
Delete: remove YAML entry (+ optional delete script).

### 8.5 "I added a new script — where do I put it so the pipeline can run it?"

**Checklist (minimum):**

1. **Place the file**
   - Standard inventory combiner → `report_script/common_sanity_report/my_report.py`
   - Orders → `report_script/orders/my_report.py`
   - Built on sanity outputs → `report_script/requirement_specific/my_report.py`
   - One-off utility → `report_script/utility_codes/` (or `other_scripts/`; register in `report.yaml` for menu)

2. **Implement**

```python
def run(*, client: str = "ESH", geos=None, **kwargs):
    # load via config_manager.layouts / get_client / sku cleaners
    # write to paths.sanity_data_root() / client / "<subdir>"
    ...
```

3. **Register** in `config_manager/report.yaml`:

```yaml
report_stages:
  common:
    label: "Stage: common"
    order: 2

reports:
  my_report:
    label: My Report
    stage: common
    module: report_script.common_sanity_report.my_report
    output_subdir: my_report   # omit if not writing to sanity_data/
    menu_order: 6
    enabled: true
```

4. **Package import** — folder must have `__init__.py` (already present for the main packages).

5. **Layouts / SKU** — if the script needs KNC folder roots or COGS sheets, use `layouts.py` + existing cleaners; extend layouts if paths are new.

6. **Run** — `python run_pipeline.py` → your label appears under Reports.

**Files you typically touch for a new runnable report:**

| Must | Sometimes |
|------|-----------|
| New `report_script/.../my_report.py` | `layouts.py` (new relative paths) |
| `config_manager/report.yaml` | `*_sku_cleaning.py` |
| This `project_structure.md` | `client.yaml` / `geography.yaml` (only if new client/geo) |
| | `.env` (only if new path vars) |

---

## 9. Requirement-specific reports (not in main menu yet)

Registered under `report.yaml` → `requirement_reports` (mostly `enabled: false`).  
Wire a `module` + `enabled: true`, then either:

- add them to the main `reports:` block so the CLI menu shows them, **or**
- re-enable a dedicated post-run / stage menu later.

Examples: instock (`d_inventory_supply_chain.py`), total inventory, city/state orders (`orders_pincode.py`).

---

## 10. Quick reference — "I want to…"

| Goal | Primary files |
|------|----------------|
| Change my machine paths | `.env` only |
| Add client | `client.yaml`, `.env`, `geography.yaml`, `layouts.py`, SKU + report configs |
| Add geo | `client.yaml`, `geography.yaml`, `layouts.py`, `run_pipeline.py` (`GEO_OPTIONS`) |
| Add report to menu | new script + `report.yaml` (+ layouts if needed) **or** Portal → Developer → Add Report |
| Disable report | `report.yaml` → `enabled: false` **or** Portal → Report Registry |
| Disable client | `client.yaml` → `enabled: false` |
| Change COGS sheet name | `geography.yaml` |
| Shared load/merge helpers | `config_manager/report_helpers.py` |
| Change CLI menus / post-run loop | `run_pipeline.py` |
| Document any of the above | **this file** |

---

## 11. Related docs

- `brain/README.md` — knowledge base index  
- `brain/config.md` — config loader notes  
- `brain/pipeline-stages.md` — stage history (stages currently unused in CLI)  
- `brain/overview.md` — short client/geo overview  
