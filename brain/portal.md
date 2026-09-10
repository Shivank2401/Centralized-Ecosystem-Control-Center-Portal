# Portal (Inventory Ecosystem Portal)

## Status
**Configuration Management Center complete** (on top of Phase 6): structured editors + raw YAML + history over `config_manager/`.

## Configuration APIs
`/api/config/overview|validate|clients|geographies|reports|stages|sequences|environment|files|history`

## Config → Reports UI
- Route: `/config/reports` — browse `report_script/` packages (same card layout as former Script packages page)
- Package detail: `/config/reports/:packageName` — list scripts + registration status (no per-script Run; use Pipeline / CLI for interactive scripts)
- Sidebar **Reports** section removed; old `/reports*` routes redirect here

## Reports menu → report_script browser
Removed as a top-level menu. API `GET /api/report-scripts` still powers Configuration → Reports.

## Stage key aliases
`pipeline_engine.registry.normalize_stage_key` maps legacy report `stage` strings onto `report_stages` keys:
- `Common Sanity Reports` / `amazon_reportss` → `common`
- `Supply Chain` / `supply_chain` → `helper_files_nd_saving`
Without this, Configuration → Stages showed **0 reports** for those packages even though scripts exist.

## Interactive scripts in portal runs
Portal workers set `PIPELINE_NON_INTERACTIVE=1` and have no TTY. Scripts that call `input()` must:
1. Accept explicit kwargs/CLI flags (e.g. MEIR `month=` / `--report-month`), and/or
2. Use `pipeline_engine.interactive.safe_input` / `stdin_is_interactive()` and fall back to defaults (never raise EOFError).

MEIR Finance: non-interactive → previous calendar month; override with `MEIR_REPORT_MONTH=Nov-2025`.

## Run Detail live UX
- Live logs auto-scroll to the latest output (pauses if the user scrolls up).
- Overall progress advances per geography for geo-scoped reports (common sanity, etc.), not only 0→100 when the whole report finishes.
- Each report script prints `[SUCCESS] <script> completed successfully.` via `print_script_completed` (pipeline executor + CLI `__main__`).

## Rules
- `config_manager/*.yaml` remains the only registry
- `.env` stays machine-local; secrets never sent to the browser
- Backups: `runtime/config_backups/`
- Do not use Add Report upload for config editing

## Next
Phase 7 — Documentation synchronization (separate).
Optional: portal UI fields for report-specific params (month, azure upload, etc.).
