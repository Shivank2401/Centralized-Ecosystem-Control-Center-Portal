# Shipping Queue (ESH)

## Script
- `report_script/shipping_queue/esh_shipping_queue.py`
- Stage: `shipping_queue` (`report.yaml` + `STAGE_PATHS`)
- Report code: `esh_shipping_queue` (ESH only)

## Geos
- Pipeline/CLI `geos=` / `--countries` (no `.env` `cogs_sheet_*`)
- Fallback when ALL: amazon geos from `geography.yaml` via `layouts.cogs_sheets_for`

## SKU / COGS
- Same cleaner as orders (`esh_sku_cleaning`), with `drop_missing=False` + restore merchant SKU when no COGS master match (so shipment lines are not wiped)
- Mapping from local `cogs/esh/{cc}_amazon_cogs` via `load_sku_mapping(geos=[CC], channel="amazon")`

## IO
- **Raw in:** `CONTAINER_NAME_ESH_RAW` → `data_dump/shipping_queue/amazon/YYYY/MM/DD/{cc}_shipments_summary.csv`
- **Local:** `sanity_data/ESH/shipping_queue/{COUNTRY_CODE}_amazon_shipping_queue.csv|.parquet`
- **Azure out:** `CONTAINER_NAME_ESH` → `sanity_data/shipping_queue/{COUNTRY_CODE}_amazon_shipping_queue.csv|.parquet`
  (e.g. `UK_amazon_shipping_queue.csv` + `.parquet`)

## Run
```bash
python report_script/shipping_queue/esh_shipping_queue.py --countries US,AE
# pipeline: run(client='ESH', geos=['US'])
```
