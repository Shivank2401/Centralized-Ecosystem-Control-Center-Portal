# Inventory database

Module: `report_script.amazon_reports.inventory_database`

Notebook source: `report_script/amazon_reports/inventory_database.ipynb` (ESH US).

Standard-dataset combiner for **ESH and KNC**, all client geos.

## Inputs
| Source | Path |
|--------|------|
| Manage FBA | `sanity_data/{CLIENT}/manage_fba/{GEO}_manage_fba_inventory.parquet` |
| Reserved | `sanity_data/{CLIENT}/reserved/{GEO}_reserved_inventory.parquet` |
| Ageing | `sanity_data/{CLIENT}/ageing/{GEO}_ageing_inventory.parquet` |

Run after those three common reports.

## Logic (same as notebook)
1. Merge manage_fba ← reserved on `geography, platform, date, sku` (left)
2. Merge ageing (`geography, date, sku, fc_transfer`) (left)
3. `fillna(0)`
4. Ageing date: **US / CA +1 day**, other geos +0
5. FC transfer:
   - AE / IN → `ageing.fc_transfer` if nonzero, else `reserved.reserved_fc_transfers`
   - other → `afn_fc_transfer_quantity` if nonzero, else `reserved.reserved_fc_transfers`
6. If `afn_reserved_quantity` is 0, use `reserved.reserved_qty`
7. Drop source FC/reserved helper columns; keep `afn_fc_transfer_quantity`

## Output
```
sanity_data/{CLIENT}/inventory_database/{GEO}_inventory_database.parquet
sanity_data/{CLIENT}/inventory_database/{GEO}_inventory_database.csv
sanity_data/{CLIENT}/logs/inventory_database/latest.log   # new SKUs + per-geo checklist
```

Stock status (Overstock / Understock / Healthy) is computed in `vector_report_amazon`, not here — see `sanity_data/{CLIENT}/logs/vector/latest.log`.

## Run
```bash
python report_script/amazon_reports/inventory_database.py --client ESH
python report_script/amazon_reports/inventory_database.py --client KNC --geos UK,DE,AE
```

Pipeline: Stage **common** → Inventory Database.
