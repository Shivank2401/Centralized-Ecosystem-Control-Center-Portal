# Shipping Queue (ESH + KNC)

## Script
- **Preferred:** `report_script/shipping_queue/shipping_queue_report.py`
- Stage: `shipping_queue` (`report.yaml` + `STAGE_PATHS`)
- Report code: `shipping_queue_report` (clients: ESH, KNC)
- Legacy wrappers (disabled in YAML): `esh_shipping_queue.py`, `knc_shipping_queue.py`

## Geos
- Pipeline/CLI `geos=` / `--geos` / `--countries` (no `.env` `cogs_sheet_*`)
- Fallback when ALL: amazon geos from `geography.yaml` via `layouts.cogs_sheets_for`

## SKU / COGS
- ESH: `esh_sku_cleaning` (same as orders)
- KNC: `knc_sku_cleaning` (same as orders; AE may use `sku_source_by_geo`)
- Keep merchant SKU when cleaner yields null (shipment lines retained)

## IO
- **Raw in:** `CONTAINER_NAME_{ESH|KNC}_RAW` (fallback `CONTAINER_NAME_{ESH|KNC}`)
  → `data_dump/shipping_queue/amazon/YYYY/MM/DD/{cc}_shipments_summary.{json|csv|parquet}`
- **Local:** `sanity_data/{CLIENT}/shipping_queue/{GEO}_amazon_shipping_queue.csv|.parquet`
- **Azure out:** `CONTAINER_NAME_{ESH|KNC}` → `sanity_data/shipping_queue/{GEO}_amazon_shipping_queue.csv|.parquet`

## Run
```bash
python report_script/shipping_queue/shipping_queue_report.py --client ESH --geos US,AE
python report_script/shipping_queue/shipping_queue_report.py --client KNC --geos UK,DE
# pipeline: run(client='ESH', geos=['US'])  # executor runs each selected client
```
