# Pincode master export

Module: `report_script.want_to_update.pincode`

Builds per-geo Amazon pincode CSVs from ESH `pincode.xlsx` (AE is a hardcoded ship-city map).

## Input
| Env | Default |
|-----|---------|
| `ESH_PINCODE_PATH` | `{ESH_DATA_ROOT}/dashboard_essential_files/pincode.xlsx` |

Sheets: USA, Canada, Germany, UK, India, Ireland (+ AE hardcoded).

## Local output
```
pincode/{cc}_amazon_pincode.csv
```
Examples: `us_amazon_pincode.csv`, `uk_amazon_pincode.csv`, `ae_amazon_pincode.csv`.

Point `PINCODE_DATA_DIR` at this folder (or leave unset so it falls back to `{project_root}/pincode`) for `orders_pincode`.

## Azure
- Container: same as COGS helpers (`COGS_AZURE_CONTAINER` / `ITEM_MASTER_CONTAINER` / `app-helper`)
- Blob: `pincode/{cc}_amazon_pincode.csv`

## Run
```bash
python report_script/want_to_update/pincode.py
python report_script/want_to_update/pincode.py --geos UK,AE --skip-azure
```

Pipeline: Stage **want_to_update** → Pincode (always all geos, including IE).
