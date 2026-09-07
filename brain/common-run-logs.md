# Common report run logs

Module: `report_script.common_sanity_report.run_logs`

After each common (and vector) report run, open a text file instead of scrolling the terminal.

## Paths

```
sanity_data/{CLIENT}/logs/{report}/{YYYYMMDD_HHMMSS}.log
sanity_data/{CLIENT}/logs/{report}/latest.log
```

### Missing SKUs vs COGS (full list CSV)

When any geo has SKUs missing from the COGS sheet, a CSV is written (no 50-row terminal cap):

```
sanity_data/{CLIENT}/logs/new_skus_vs_cogs/{report}/latest.csv
sanity_data/{CLIENT}/logs/new_skus_vs_cogs/{report}/{YYYYMMDD_HHMMSS}.csv
```

Columns: `client`, `report`, `geography`, `sku`, `run_at`

Example: `sanity_data/ESH/logs/new_skus_vs_cogs/ageing/latest.csv` after ageing report.

`latest.log` always mirrors the most recent run for that client + report.

## What each log contains

| Report | Load summary + geo×year | New SKUs vs COGS | Orders period | Stock status |
|--------|-------------------------|------------------|---------------|--------------|
| manage_fba / reserved / ageing / ledger | yes | yes | — | — |
| orders | yes | yes | current + previous month rows/qty/sales per geo | — |
| inventory_database | combined row counts | yes (per geo) | — | n/a (see vector) |
| vector | geo checklists | yes | previous-month orders in checklist | Overstock / Understock / Healthy |

## Example (orders)

```
[AE] current month orders (2026-08): rows=120 | qty=1,200 | total_sales_sum=45,000.00 | previous month qty=1,100 | previous_month total_sales_sum=42,000.00
```

## Wired scripts

- `manage_fba_report.py`, `reserved_report.py`, `ageing_report.py`, `ledger_report.py`
- `orders_report.py`
- `inventory_database.py`
- `requirement_specific/vector_report.py` (stock status lives here)
