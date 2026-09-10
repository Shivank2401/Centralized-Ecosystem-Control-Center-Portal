# COGS export (ESH + KNC)

## Update Azure (Excel → blob)
Modules under `report_script/want_to_update/`:
- `esh_cogs.py` — ESH sheets → Azure only
- `knc_cogs.py` — KNC sheets → Azure only
- Shared I/O: `cogs_io.py`

## Download local (Azure → project `cogs/`)
Module: `report_script/supply_chain/d_download_cogs.py`

Writes:
```
cogs/{esh|knc}/{stem}_cogs.parquet|.csv
```

## Inputs (upload)
| Client | Env | Sheets |
|--------|-----|--------|
| ESH | `ESH_COGS_PATH` | ESH-UK, ESH-CA, ESH-USA, ESH-UAE, ESH-IN, ESH-DE |
| KNC | `KNC_COGS_PATH` | Main (UK amazon), Shopify (UK + IE shopify), Germany-COGS, KCA-AE |

`client_id` comes from `client.yaml`.

## Consumer source (report scripts)
SKU mapping / master SKU lookups use local slices via `config_manager.cogs_local`:

```
cogs/{esh|knc}/{country}_amazon_cogs.parquet
```

Refresh local copies with **Download COGS** before relying on SKU cleaners.

Wired through:
- `esh_sku_cleaning` / `knc_sku_cleaning` (`load_cogs_helper_frame`, `load_sku_mapping`)
- common sanity reports (ageing, ledger, manage_fba, reserved, orders)
- `amazon_reports.new_sku_check`
- shipping queues (local first, Azure fallback)

## Azure
- Container: `COGS_AZURE_CONTAINER` → else `ITEM_MASTER_CONTAINER` → else `app-helper`
- Blob prefixes: `thrive-client-ecosoulhome/cogs/` (ESH), `thrive-client-kinetica/cogs/` (KNC)
- USA Azure CSV stem stays `usa_amazon_cogs` (parquet uses `us_amazon`)

No MySQL upload.

## Run
```bash
# Upload Excel → Azure
python report_script/want_to_update/esh_cogs.py --geos UK,US
python report_script/want_to_update/knc_cogs.py --geos UK,DE

# Download Azure → local cogs/{client}/
python report_script/supply_chain/d_download_cogs.py --client ESH
python report_script/supply_chain/d_download_cogs.py --client ALL
```

Pipeline:
- Stage **want_to_update** → ESH COGS / KNC COGS (Azure upload)
- Stage **supply_chain** → Download COGS (Azure → local)
