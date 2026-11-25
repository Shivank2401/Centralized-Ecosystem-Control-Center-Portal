# MBR Report (Monthly Business Report)

## Module
`report_script.amazon_reports.MBR_report` → `report_script/amazon_reports/MBR_report.py`

Notebook source (US ESH prototype): `report_script/mbr_report/monthly_business_report.ipynb`

## Clients / geos
- **ESH** + **KNC** — amazon channel geos from `client.yaml` / `layouts.geos_with_channel`
- Per-geo build (same `CLIENT_CONFIGS` pattern as `ageing_report.py`)

## Inputs (sanity_data)
| Source | Prefer | Fallback |
|--------|--------|----------|
| Orders | `{GEO}_amazon_orders_database.parquet` | `{GEO}_orders_database.parquet` |
| Inventory DB | `{GEO}_amazon_inventory_database.parquet` | `{GEO}_inventory_database.parquet` |
| Ageing | `{GEO}_amazon_ageing_inventory.parquet` | `{GEO}_ageing_inventory.parquet` |
| Ledger | `{GEO}_amazon_ledger_inventory.parquet` | `{GEO}_ledger_inventory.parquet` |
| Returns (ESH) | `{GEO}_amazon_return_database.parquet` | soft-skip if missing |
| Ads | single all-geo CSV (see below) | ad metrics = 0 |
| Material | local COGS via `cogs_local` (`channel=amazon`) | material cols blank |

## Ads (important)
One Executive file holds **all geos**:
`final_adsales_grosssales.csv` (`country` = USA / CA / UK / DE / AE / IN).

- Load **once**, then filter `country` for the current geo.
- Portal `US` → file `USA` (aliases also accept US).
- Do **not** hardcode `df_ads[df_ads["country"] == "USA"]` for multi-geo runs.
- Path: `ESH_MBR_ADS_PATH` / `MBR_ADS_PATH`, else ESH `default_ads_path` in `CLIENT_CONFIGS`.
- KNC: set `KNC_MBR_ADS_PATH` when a KNC all-geo ads file is available.

## Outputs
- Local: `sanity_data/{CLIENT}/mbr/{GEO}_amazon_mbr_sku.parquet|.csv`
- Local: `sanity_data/{CLIENT}/mbr/{GEO}_amazon_mbr_material.parquet|.csv`
- Azure: `{CONTAINER_NAME_{ESH|KNC}}/sanity_data/mbr_report_database/{same parquet names}`
- Run log: `sanity_data/{CLIENT}/logs/mbr/`

## Metrics (notebook)
Orders monthly × ledger instock (EIQ = sell_thru×30) × latest inventory+ageing snapshot × ads × returns → contribution %, MoM/YoY growth, ACOS/TACOS/ROAS, inventory age risk, ad dependency / cannibalization alerts. Material roll-up pivots numeric cols by material / category dims.

## CLI
```
python report_script/amazon_reports/MBR_report.py --client ESH
python report_script/amazon_reports/MBR_report.py --client KNC --geos UK,DE,AE --no-azure
```

## report.yaml
`mbr_report` → stage `amazon_reports`, `output_subdir: mbr`, clients ESH + KNC.
