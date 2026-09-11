# Inventory Ecosystem Portal — Architecture

**Repo root:** `C:\Developer data\Centralized Ecosystem Portal\`  
**Status:** Phase 2 implemented (React shell + dashboard + pipeline wizard + reports)  
**Date:** 2026-09-07  
**Principle:** Portal orchestrates existing ETL — does not rewrite report scripts.  
**Source of truth (existing pipeline):** `config_manager/project_structure.md`

Do **not** nest under a new `client_pipeline/` folder. New layers live beside `config_manager/` and `report_script/`.

---

## 1. Current architecture assessment

| Layer | Location | Role |
|-------|----------|------|
| CLI | `run_pipeline.py` (~1100 lines) | Interactive menus + argparse + importlib dispatch |
| Config | `config_manager/*.yaml` + `.env` | Clients, geos, reports, sequences; machine paths in `.env` |
| Loaders | `loader.py`, `paths.py`, `layouts.py` | YAML → dataclasses; env → Path |
| ETL | `report_script/**` | Pandas reports; most expose `run(*, client, geos, **kwargs)` |
| Outputs | `sanity_data/`, `cogs/`, `pincode/` | Parquet/CSV (paths often via `.env`) |
| Docs | `brain/`, `project_structure.md` | Operator knowledge |

**Strengths:** Clear `run()` contract; portable YAML vs local `.env`; client/geo scoping in `report.yaml`.  
**Gaps for portal:** Execution mixed into CLI; no run IDs / API / UI; report registration is hand-edited YAML.

---

## 2. Existing execution flow

```text
python run_pipeline.py [--client|--geo|--report|--stage|--sequence]
        ↓
execute(clients, geos, reports)
        ↓
for report in order:
  for client in clients:
    filter geos → importlib.import_module(meta.module).run(client=, geos=)
        ↓
report writes sanity_data/{CLIENT}/… (+ own logs)
```

---

## 3. Reuse as-is

- All of `report_script/**`
- `config_manager` loaders, YAML, SKU/COGS helpers
- `.env` / `.env.example` contract
- `brain/**` (never delete)
- CLI interactive UX (menus stay in `run_pipeline.py`)

---

## 4. Needs refactoring

| Item | Change |
|------|--------|
| `run_pipeline.py` | Keep menus; delegate `execute` → `PipelineExecutor` |
| (new) `pipeline_engine/` | Shared registry, validation, executor, run_manager |
| (new) `backend/` | Thin FastAPI over engine |
| (new) `runtime/` | Run artifacts |
| `requirements.txt` | Add FastAPI / uvicorn |

---

## 5. Proposed architecture

```text
React (Phase 2+)
    ↓
FastAPI  backend/
    ↓
pipeline_engine/     ← single execution boundary
    ↓
config_manager/ + report_script/
```

```text
CLI (run_pipeline.py) ──┐
                        ├──► PipelineExecutor
FastAPI ────────────────┘
```

---

## 6. Migration plan

| Phase | Scope | Status |
|-------|--------|--------|
| **1** | Architecture + pipeline_engine + FastAPI read APIs + CLI via executor | Done |
| **2** | React shell (sidebar, dashboard, run wizard, reports) | Done |
| **3** | Background runs / logs / history / cancel | **Done** |
| **4** | Connect UI↔API↔pipeline (diagnostics, env, validate, sequences) | **Done** |
| **5** | Add Report upload / AST / stage / register / registry | **Done** |
| **6** | Diagnostics + Outputs / Logs / COGS / Pincode explorers | **Done** |
| 7–8 | Docs sync, optional extras | Pending |

Priority: **ETL stability > abstraction > API > frontend > automation**

---

## 7. Risks

| Risk | Mitigation |
|------|------------|
| Breaking CLI | Menus unchanged; thin executor wrapper; smoke-test flags |
| Stage label vs key mismatch (`Amazon Reports` / legacy `Common Sanity Reports` vs `common`) | Centralize `normalize_stage_key` |
| Concurrent file access | One active run (Phase 3+) |
| Uploaded Python (later) | AST-only validate; subprocess isolation |

---

## 8. Phase 1 plan

1. Add `pipeline_engine/` (registry, discovery, validation, executor, run_manager, models).
2. Refactor `run_pipeline.py` `execute` / dispatch to use `PipelineExecutor`.
3. Preserve: `python run_pipeline.py`, `--client/--geo/--report`, `--sequence`.
4. FastAPI: `/api/health`, clients, geographies, stages, reports, sequences.
5. `portal.py` launcher; `runtime/`; tests; update `brain/`.

**Non-goals Phase 1:** React, background workers, report upload.
