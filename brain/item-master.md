# Item Master Manager

Module: `report_script.item_master.item_master_manager`

## Azure layout
```text
container : app-helper
blob      : item_master/{CLIENT}.parquet
```

Examples:
- `app-helper` / `item_master/ESH.parquet`
- `app-helper` / `item_master/KNC.parquet`

Geo/channel are **columns** inside the file, not folders.

Env:
- `ITEM_MASTER_CONTAINER` (default `app-helper`, or `CONTAINER_NAME_ESH`)
- `ITEM_MASTER_BLOB_PREFIX` (default `item_master`)

## Import by client / geo / channel
Menu **1. Import file**:
1. Path to Excel / CSV / Parquet
2. Sheet name (Excel only)
3. Client → Geography → Channel
4. Downloads the client file, **replaces only that geo/channel slice**, optional upload

**Important:** same client + same channel + **different geo** → both geos stay in the parquet.
Only the matching `(geo, channel)` slice is replaced; other slices are kept.

## View table
Menu **3. View table**:
- Download client parquet
- Show row counts by geo/channel
- Filter and print rows (optional CSV export)

## Local cache
`sanity_data/item_master/{CLIENT}.parquet` (+ `.csv`)

## Pipeline
Stage key: `item_master` (ESH + KNC) via `run_pipeline.py`.
