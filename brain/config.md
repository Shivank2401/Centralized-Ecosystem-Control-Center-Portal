# Config manager

## Files
| File | Role |
|------|------|
| `client.yaml` | Client registry; `data_root_env` / `cogs_path_env` point at .env keys |
| `geography.yaml` | Per-client geo: COGS sheet, currency, sales channel |
| `report.yaml` | CLI reports + stages → Python modules |
| `paths.py` | Resolve paths from `.env` via python-dotenv |
| `loader.py` | `load_clients()`, `load_geographies()`, `get_client()` |
| `layouts.py` | ESH geo folders + KNC relative roots under data_root |
| `report_helpers.py` | Shared LoadStats, parquet merge, to_snake (replaces ecosoul.manage_fba_database) |
| `esh_sku_cleaning.py` / `knc_sku_cleaning.py` | SKU + COGS mapping (COGS path from .env) |
| `orders_pincode.py` | Pincode → city/state (`PINCODE_DATA_DIR` from .env) |

## Rule
No hardcoded user paths. Paths live in `.env` so any user can run the pipeline.
MySQL utility credentials (`MYSQL_*`) also live in `.env` — never commit passwords.

## Loader usage
```python
from config_manager import get_client, load_geographies, paths, layouts

client = get_client("ESH")
root = client.data_root          # from ESH_DATA_ROOT
cogs = client.cogs_path          # from ESH_COGS_PATH
geos = load_geographies("ESH")
knc_ledger = layouts.knc_geo_roots("ledger")
```
