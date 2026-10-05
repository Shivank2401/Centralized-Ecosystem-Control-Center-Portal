# Shopify ledger (KNC UK + IE)

## Module
`report_script.shopify_reports.ledger_shopify`

## Stage
`shopify_reports` → package `report_script/shopify_reports`  
Pipeline: **non-geo-scoped** (one job per client; UK+IE in that job).

## Geos
From `geography.yaml` → geos with `channels.shopify` (UK + IE for now).

## Env paths
```
KNC_SHOPIFY_UK_LEDGER_ROOT=.../Shopify/uk/inventory_ledger
KNC_SHOPIFY_IE_LEDGER_ROOT=.../Shopify/ie/inventory_ledger
```

Layout:
```
{ROOT}/Month-end inventory snapshot- Current Month.csv   # optional live
{ROOT}/Month-end inventory snapshot- Last Month.csv      # optional live
{ROOT}/Year/2026/Inventory ledger_Apr-2026.csv           # preferred archives
{ROOT}/Year/2025/...                                     # when present
```

Drop new month files under `Year/{YYYY}/` (name like `Inventory ledger_Apr-2026.csv`).  
Amazon-format CSVs accidentally placed here are **skipped** with a warning.

## Year / month knobs
```python
VALID_YEARS = {"2025", "2026"}
PROCESS_YEARS: Optional[List[str]] = ["2025", "2026"]
PROCESS_MONTHS: Optional[List[str]] = None  # None = all month files under each year
INCLUDE_ROOT_LIVE = True  # Current / Last Month at ledger root
```

## SKU
`knc_sku_cleaning.clean_sku_column(..., source="shopify")`

## Date
Aligned with `amazon_reports/ledger_report.py`:
- ISO `YYYY-MM-DD` (Shopify Day) → `pd.to_datetime`
- Ambiguous `DD/MM` / `MM/DD` → same intentional day/month swap as Amazon ledger

## Transform (Amazon ledger style)
1. Load Year/{PROCESS_YEARS} CSVs (+ optional root live)
2. Normalize Shopify columns → rename to sku / Date / ending_balance
3. SKU clean → date clean → groupby sku+date sum ending_balance
4. Output cols: `client, client_id, geography, platform=shopify, date, year_month, sku, ending_balance`
   (`year_month` = `date.dt.strftime("%Y-%m")` after daily agg)

## Dedupe / merge
Keys: `client`, `geography`, `date`, `sku`  
Same pattern as ledger / manage_fba / Shopify inventory: dedupe new → merge_append_dedupe → save  
`sanity_data/KNC/ledger/{GEO}_shopify_ledger_inventory.parquet|.csv`  
Does **not** touch `{GEO}_ledger_inventory.*` (Amazon).

## Run
```bash
python report_script/shopify_reports/ledger_shopify.py --client KNC
python report_script/shopify_reports/ledger_shopify.py --geos UK,IE --no-merge
python report_script/shopify_reports/ledger_shopify.py --no-root-live
```
