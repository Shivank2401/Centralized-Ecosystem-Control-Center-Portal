# Shopify orders (KNC UK + IE)

## Module
`report_script.shopify_reports.orders_report`

## Stage
`shopify_reports` → package `report_script/shopify_reports`

## Geos
Geo is defined by **sales root folder** (`KNC_SHOPIFY_{GEO}_SALES_ROOT`), not by Market/vendor filters.

### Market / vendor bookmark (`geography.yaml` → `channels.shopify`)
Kept for reference / sell_thru. **`orders_report.py` does not filter on these.**

| Geo | markets (bookmark) | vendors (bookmark) | currency |
|-----|--------------------|--------------------|----------|
| UK | `United Kingdom` | `Kinetica - UK`, `Kinetica Sports UK` | GBP |
| IE | `Ireland`, `International` | `Kinetica - IE`, `Kinetica Sports`, `Kinetica Sports IE` | EUR |

IE is registered in `geography.yaml` / `client.yaml` for KNC.

## Env paths
```
KNC_SHOPIFY_UK_SALES_ROOT=.../Shopify/uk/sales/Year
KNC_SHOPIFY_IE_SALES_ROOT=.../Shopify/ie/sales
```

## Process (per geo, after all year CSVs appended)
1. Select required columns
2. Drop rows where `purchase_hour` is blank
3. Qty / signed `total_sales` clean (keep refunds with qty=0 and sales&lt;0)
4. Parse datetime → `purchase_date` / `year_month` / `purchase_time`
5. SKU clean+map (`knc_sku_cleaning`, `source=shopify`); missing SKU → **`Not defined`** (not dropped)
6. Pivot → pincode city/state → Shopify COGS merge; missing **`product_name` → `Not defined`**
7. Print new SKUs present in orders but not in Shopify COGS (excludes `Not defined`)

## Signed total_sales (refunds)
Shopify refunds often have `Total sales < 0` with `Quantity ordered == 0`.
ETL keeps rows where `quantity != 0` **or** `total_sales != 0` (never `abs()` on sales).

## COGS
Local only:
```
cogs/knc/uk_shopify_cogs.csv
cogs/knc/ie_shopify_cogs.csv
```

## Output
```
sanity_data/KNC/orders/{GEO}_shopify_orders_database.parquet
sanity_data/KNC/orders/{GEO}_shopify_orders_database.csv
```
Does **not** merge into Amazon `{GEO}_orders_database.*`. Schema matches Amazon orders columns (`platform=shopify`) plus `product_name`. Uses **`geography` only** (not a duplicate `country` column).

## Note
Many blank SKUs collapse into one pivot key `Not defined` (qty/sales summed together).

## Run
```bash
python report_script/shopify_reports/orders_report.py --client KNC
python report_script/shopify_reports/orders_report.py --geos UK,IE --years 2026
```
