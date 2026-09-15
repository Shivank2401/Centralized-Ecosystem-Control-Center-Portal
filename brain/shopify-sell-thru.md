# Shopify Sell-Thru (KNC UK + IE)

## Module
`report_script.shopify_reports.sell_thru`

## Stage
`shopify_reports` → package `report_script/shopify_reports`  
Pipeline: **non-geo-scoped** (one job per client; UK+IE in that job).  
**Standalone** — does **not** merge into Shopify orders.

## Geos
From `geography.yaml` → geos with `channels.shopify` (UK + IE).

## Env paths (reuse sales roots — no new keys)
```
KNC_SHOPIFY_UK_SALES_ROOT=.../Shopify/uk/sales/Year   # or .../sales
KNC_SHOPIFY_IE_SALES_ROOT=.../Shopify/ie/sales
```

Resolved Sell-thru folders:
```
UK: {sales}/Sell-thru/Sell-thru {YYYY}.csv
IE: {sales}/Sell-thru/…  OR  sibling {ie}/sell_thru/Sell-thru {YYYY}.csv
```

## Year knobs
```python
VALID_YEARS = {"2024", "2025", "2026"}
PROCESS_YEARS: Optional[List[str]] = ["2024", "2025", "2026"]
```
Year is taken from the filename (`Sell-thru 2026.csv`).

## Vendor filter (exact lists, right after raw append)
- **UK:** `Kinetica - UK`, `Kinetica Sports UK`
- **IE:** `Kinetica - IE`, `Kinetica Sports`, `Kinetica Sports IE`

Then pivot: `sum(Sell-through rate)` on `Day` + `Product variant SKU` (per geography), then SKU clean.

## Output columns
`client, client_id, geography, platform=shopify, date, sku, sell_thru`

## Dedupe / merge
Keys: `client`, `geography`, `date`, `sku`  
`merge_append_dedupe` → `sanity_data/KNC/sell_thru/{GEO}_shopify_sell_thru.parquet|.csv`

## Run
```bash
python report_script/shopify_reports/sell_thru.py --client KNC
python report_script/shopify_reports/sell_thru.py --geos UK,IE --years 2025,2026 --no-merge
```
