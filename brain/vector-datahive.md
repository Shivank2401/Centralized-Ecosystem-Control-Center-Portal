# Vector Datahive

Module: `report_script.requirement_specific.vector_report`

Requirement-specific Amazon inventory snapshot for **ESH and KNC**.
Notebook source: `report_script/requirement_specific/vector_report.ipynb`.

## Inputs (standard dataset)
| Source | Path |
|--------|------|
| Manage FBA | `sanity_data/{CLIENT}/manage_fba/{GEO}_manage_fba_inventory.parquet` |
| Reserved | `sanity_data/{CLIENT}/reserved/{GEO}_reserved_inventory.parquet` |
| Ledger | `sanity_data/{CLIENT}/ledger/{GEO}_ledger_inventory.parquet` |
| Ageing | `sanity_data/{CLIENT}/ageing/{GEO}_ageing_inventory.parquet` |
| Orders | `sanity_data/{CLIENT}/orders/{GEO}_orders_database.parquet` |
| COGS | `cogs/{client}/{geo}_amazon_cogs.parquet` |

Snapshot date: today → yesterday → latest available.

## Checklist (per client / geo)
Printed once after all geos finish (ordered), not interleaved by threads.
Also written to `sanity_data/{CLIENT}/logs/vector/latest.log`.

1. **Files read** — name, row count, date range in file, snapshot date used (manage / reserved / ageing)
2. **Previous-month orders** — row count + `total_sales` sum
3. **Stock status** — Overstock / Understock / Healthy counts
4. **New SKUs** — SKUs present in inventory before COGS filter but missing from the COGS sheet
5. **Final output rows**

Current-month orders are **not** used (only previous-month orders feed MTQ thresholds) and are dropped after load.

## FC transfer qty
Applied **per geography** inside each worker thread:

| Geos | Source column |
|------|----------------|
| AE, IN | `ageing.fc_transfer` |
| All others | `manage_fba.afn_fc_transfer_quantity` |

If that source is **0**, fall back to `reserved.reserved_fc_transfers`.
Final column is renamed back to `afn_fc_transfer_quantity`.

## Output
```
sanity_data/{CLIENT}/vector_report/{geo}_{platform}_inventory_report.parquet
sanity_data/{CLIENT}/vector_report/{geo}_{platform}_inventory_report.csv
```
Example: `sanity_data/ESH/vector_report/us_amazon_inventory_report.parquet`

## Run
```bash
python report_script/requirement_specific/vector_report.py --client ESH --geos US,AE,IN
python report_script/requirement_specific/vector_report.py --client KNC
```

Pipeline: Stage **requirement_specific** → Vector Datahive.
Geos run in parallel threads (`--workers`, default 4).
