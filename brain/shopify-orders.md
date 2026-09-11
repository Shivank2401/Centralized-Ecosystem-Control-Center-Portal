# Shopify orders (KNC UK + IE)

## Module
`report_script.shopify_reports.orders_report`

## Stage
`shopify_reports` → package `report_script/shopify_reports`

## Geos
- **UK** — Market `United Kingdom`; vendors `Kinetica - UK`, `Kinetica Sports UK`; currency GBP
- **IE** — Markets `Ireland`, `International`; vendors `Kinetica - IE`, `Kinetica Sports`, `Kinetica Sports IE`; currency EUR

IE is registered in `geography.yaml` / `client.yaml` for KNC.

## Env paths
```
KNC_SHOPIFY_UK_SALES_ROOT=.../Shopify/uk/sales/Year
KNC_SHOPIFY_IE_SALES_ROOT=.../Shopify/ie/sales
```

## COGS
Local only:
```
cogs/knc/uk_shopify_cogs.csv
cogs/knc/ie_shopify_cogs.csv
```
Columns used: SKU, ASIN, Product Category, Product Name (Inactive/Unknown rows kept for now).

## SKU
`knc_sku_cleaning.clean_sku_column(..., source="shopify")` — digit extract + `KCA-` prefix for UK and IE; includes `200855` → `KCA-200855`.

## Output
```
sanity_data/KNC/orders/{GEO}_shopify_orders_database.parquet
sanity_data/KNC/orders/{GEO}_shopify_orders_database.csv
```
Does **not** merge into Amazon `{GEO}_orders_database.*`. Schema matches Amazon orders columns (`platform=shopify`).

## Run
```bash
python report_script/shopify_reports/orders_report.py --client KNC
python report_script/shopify_reports/orders_report.py --geos UK,IE --years 2026
```
