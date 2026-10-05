# Vector Datahive Shopify

Module: `report_script.requirement_specific.vector_report_shopify`

Requirement-specific Shopify inventory snapshot for **KNC** (UK / IE).
Notebook source: `report_script/requirement_specific/vector_report_shopify.ipynb`.
Same process/logic as `vector_report_amazon` (snapshot, previous-month MTQ, stock_status, checklist, parallel geos).

## Inputs
| Source | Path |
|--------|------|
| Inventory Shopify | `sanity_data/KNC/manage_fba/{GEO}_inventory_shopify.parquet` |
| Ledger Shopify | `sanity_data/KNC/ledger/{GEO}_shopify_ledger_inventory.parquet` |
| Orders Shopify | `sanity_data/KNC/orders/{GEO}_shopify_orders_database.parquet` |
| Sell-Thru Shopify | `sanity_data/KNC/sell_thru/{GEO}_shopify_sell_thru.parquet` |
| COGS | `cogs/knc/{geo}_shopify_cogs.parquet` |

Snapshot date: today → yesterday → latest available (inventory required).
Sell-thru snapshot is aligned to the inventory snapshot date when available.

Shopify-only geos: when the pipeline invokes this report for an amazon-only geo (e.g. KNC DE), the job **soft-skips** instead of failing.

## Differences vs Amazon vector
- No reserved / ageing masters
- FC transfer always `0` → `total_sellable = afn_fulfillable_quantity`
- Merges `sell_thru` and computes `dos` when `sell_thru > 0.1`
- New-SKU check vs **shopify** COGS channel
- Geos: `layouts.geos_with_channel(client, "shopify")` (UK, IE)

## Checklist / logs
Printed once after all geos finish.
Written to `sanity_data/KNC/logs/vector_shopify/latest.log`.

## Output
```
sanity_data/KNC/vector_report/{geo}_shopify_inventory_report.parquet
sanity_data/KNC/vector_report/{geo}_shopify_inventory_report.csv
```

## Run
```bash
python report_script/requirement_specific/vector_report_shopify.py
python report_script/requirement_specific/vector_report_shopify.py --client KNC --geos UK,IE
```

Pipeline: Stage **Requirement Specific** → Vector Datahive Shopify.
