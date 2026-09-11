# Inventory Data Pipeline — knowledge base

Do not delete this folder.

## Purpose
Multi-client Amazon inventory ETL: raw archive → amazon reports → requirement-specific reports.

**Project root:** `C:\Developer data\Centralized Ecosystem Portal` (see `project-location.md`, `portal.md`).

## Stack decision
**Python CLI** (`run_pipeline.py`) + YAML config + pandas scripts, plus **Inventory Ecosystem Portal** (`pipeline_engine` + FastAPI; React in Phase 2+).

## Entry point
```
python run_pipeline.py
python run_pipeline.py --client ESH --geo ALL --report ALL
python portal.py          # Phase 1 API http://127.0.0.1:8000
```

## Canonical guide
→ **`config_manager/project_structure.md`** (existing pipeline — keep updated)

Portal decisions: **`docs/portal-architecture.md`**

## Config
- `config_manager/client.yaml` — clients + env var *names* for data roots / COGS
- `config_manager/geography.yaml` — per-client geo metadata
- `config_manager/report.yaml` — report → module mapping
- `.env` — actual machine paths (from `.env.example`)

See also: `overview.md`, `config.md`, `pipeline-stages.md`, `cogs.md`, `pincode.md`, `invalid-skus.md`, `vector-datahive.md`, `emami-report.md`, `atros-knc.md`, `utility-codes.md`, `inventory-database.md`, `common-run-logs.md`, `amazon-reports-folder.md`, `shopify-orders.md`, `shopify-inventory.md`, `project-location.md`, `portal.md`
