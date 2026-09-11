# Shopify inventory (KNC UK + IE)

## Module
`report_script.shopify_reports.inventory_shopify`

## Stage
`shopify_reports` → package `report_script/shopify_reports`

## Geos
From `geography.yaml` → geos with `channels.shopify` (UK + IE for now).

## Env paths
```
KNC_SHOPIFY_UK_INVENTORY_ROOT=.../Shopify/uk/inventory
KNC_SHOPIFY_IE_INVENTORY_ROOT=.../Shopify/ie/inventory
```

Layout:
```
{ROOT}/inventory_shopify.csv
{ROOT}/Year/2025/{Mon-YYYY}/Shopify_inventory_{dd-Mon-YYYY}.csv
{ROOT}/Year/2026/{Mon-YYYY}/Shopify_inventory_{dd-Mon-YYYY}.csv
```

## Year / month knobs (same pattern as ageing_report)
Edit in the script:
```python
VALID_YEARS = {"2025", "2026"}
PROCESS_YEARS: Optional[List[str]] = ["2025", "2026"]
PROCESS_MONTHS: Optional[List[str]] = None  # None = all months
```
No CLI `--months` — set `PROCESS_MONTHS` in the script when you want a subset (e.g. `["Sep-2026"]`).

## Date stamp (live archive)
Same fallback as Amazon raw archives: **US/CA → T-1**, **all other geos → T**.  
UK and IE therefore use **today (T)**.  
Archive path: `{ROOT}/Year/{YYYY}/{Mon-YYYY}/Shopify_inventory_{stamp}.csv`

## SKU
`knc_sku_cleaning.clean_sku_column(..., source="shopify")`

## Transform (manage_fba-style)
1. Load all CSVs under `Year/{PROCESS_YEARS}/` (all months when `PROCESS_MONTHS is None`)
2. Tag each file with `geography`, `year`, `month`, `source_file`, `source_path`
3. **Append** into one raw DataFrame
4. Per geography: drop `not stocked` → `knc_sku_cleaning(source=shopify)` → AFN rename →
   date from filename → pivot → merge existing → save

## Dedupe (aligned with manage_fba_report)
Keys: `client`, `geography`, `date`, `sku` (`DEDUPE_SUBSET`)
1. Dedupe **new** slice on those keys before append
2. Dedupe **existing** master (if merging)
3. `merge_append_dedupe(existing, new, subset=DEDUPE_SUBSET)` — same helper as
   `manage_fba_report.py` (concat + `drop_duplicates(..., keep="last")` so new wins)
Then save `{GEO}_inventory_shopify.parquet|.csv`

## Raw archive helper
`saving_raw_file_on_date.py` archives Shopify live drops to `Year/{YYYY}/{Mon-YYYY}/` for KNC.

## Run
```bash
python report_script/shopify_reports/inventory_shopify.py --client KNC
python report_script/shopify_reports/inventory_shopify.py --geos UK,IE
```
