# Atros — KNC PNL / ads / decomposition

Stage: **atros** (separate from `common_sanity_report`).  
Client: **KNC** only. Geos: **UK, DE, AE**.

## Modules
| Report | Module | Local masters |
|--------|--------|---------------|
| PNL | `report_script.atros_code.pnl_report` | `sanity_data/KNC/pnl/` |
| Ad sales | `report_script.atros_code.ad_sales_report` | `sanity_data/KNC/ads/` |
| Decomposition | `report_script.atros_code.decomposition_chart` | `sanity_data/KNC/decomposition_chart/` |

Shared: `atros_common.py` (geo paths under `KNC_DATA_ROOT`, SKU mapping, snake_case, geo concat/dedupe, Azure upload prompt).

## Env
| Var | Purpose |
|-----|---------|
| `KNC_DATA_ROOT` | Kinetica client DB (Bulk Operations, Transaction, …) |
| `KNC_COGS_PATH` | COGS workbook (sheets Main / Germany-COGS / KCA-AE) |
| `AZURE_STORAGE_CONNECTION_STRING` | optional upload |
| `CONTAINER_NAME_KNC` | default `thrive-client-kinetica` |

## Run
```bash
python report_script/atros_code/pnl_report.py --geos UK,DE,AE --year 2026 --month aug
python report_script/atros_code/ad_sales_report.py --year 2026 --month aug --skip-azure
python report_script/atros_code/decomposition_chart.py --year 2026 --month aug --upload-azure

# or: run_pipeline.py → KNC → Stage: atros → PNL / Ad Sales / Decomposition
```

Flow: build each geo → save `{GEO}_*.parquet/.csv` + `final_*.parquet/.csv` → yes/no Azure upload.

## Replaced (deleted)
Geo scripts (`uk_pnl`, `german_pnl`, `kinetica_uae_pnl_ad_spend`, `uk_ad_sales`, `german_ad_sales`, `decomposition_chart_{uk,de,uae}`) and helpers (`paraquetfile`, `saving_all_main_files`, `changing_names`, `kinetica_aggregate`).
