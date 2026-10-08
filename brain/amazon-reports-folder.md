# Amazon reports package folder

## Rename
`report_script/common_sanity_report/` was renamed to **`report_script/amazon_reports/`**.

## Module path
All imports and `report.yaml` modules use:

`report_script.amazon_reports.<script>`

Examples: `manage_fba_report`, `reserved_report`, `ageing_report`, `ledger_report`, `orders_report`, `inventory_database`, `new_sku_check`, `run_logs`.

## Stage routing
- Package path: `report_script/amazon_reports` (`pipeline_engine.registry.STAGE_PATHS["common"]`)
- Portal / YAML display: **Amazon Reports**
- `report_stages` key stays `common` (stable pipeline key)
- Report `stage` values should be `amazon_reports` (aliases still accept legacy `Common Sanity Reports`, `common_sanity_report`, `amazon_reportss`)

## Portal browse
Configuration → Reports lists the package as `amazon_reports` under `report_script/`.

## Geography column (not country)
Sanity outputs use **`geography` only**. Do not also write a duplicate `country` column.
- Inventory scripts (manage_fba / reserved / ageing / ledger / inventory_database) already used `geography` only.
- `orders_report` previously set both; now geography-only. `prefer_geography_column()` drops legacy `country` when merging older masters.
