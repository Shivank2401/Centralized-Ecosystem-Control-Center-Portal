# Utility codes

Modules under `report_script/utility_codes/`.

Standalone helpers (not part of the standard inventory dataset). Available via
`run_pipeline.py` → **Stage: utility_codes**.

| Script | Purpose |
|--------|---------|
| `a_import_any_file_to_mysql.py` | Import CSV/Excel → MySQL table (snake_case columns) |
| `b_check_duplicate_image.py` | Export unique image basenames from a folder → CSV |
| `c_convert_json_to_csv.py` | Flatten JSON → CSV |
| `d_export_file_to_azure.py` | Upload CSV/Parquet/Excel (etc.) → Azure blob (`esh` / `knc` / `emm`) |

## MySQL credentials
Set in `.env` (see `.env.example`):
- `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD` (**required**), `MYSQL_DATABASE`
- Optional: `MYSQL_POOL_NAME`, `MYSQL_POOL_SIZE`

## Image export knobs
- `UTILITY_IMAGE_FOLDER` / `--folder`
- `UTILITY_IMAGE_OUTPUT` / `--output` (default `image_list.csv` in cwd)

## Azure upload (`d_export_file_to_azure`)
Preferred UX: Portal **Data → Azure Upload** (file picker + container + folder + name).

Container keys map to `.env`:
| Key | Env | Default container |
|-----|-----|-------------------|
| `esh` | `CONTAINER_NAME_ESH` | `thrive-client-ecosoulhome` |
| `knc` | `CONTAINER_NAME_KNC` | `thrive-client-kinetica` |
| `emm` | `CONTAINER_NAME_EMAMI` | `thrive-client-emami` |

Credentials: `AZURE_STORAGE_CONNECTION_STRING` or account name + key.

Pipeline/CLI without prompts:
- `UTILITY_AZURE_LOCAL_PATH`
- `UTILITY_AZURE_CONTAINER_KEY` (`esh`\|`knc`\|`emm`)
- `UTILITY_AZURE_BLOB_FOLDER`
- `UTILITY_AZURE_BLOB_NAME` (optional — keep source name if empty)

API (portal page): `GET /api/azure/containers`, `GET /api/azure/folders`, `POST /api/azure/upload`.

## Run
```bash
python report_script/utility_codes/a_import_any_file_to_mysql.py --file data.csv --table my_table
python report_script/utility_codes/b_check_duplicate_image.py --folder "D:/imgs"
python report_script/utility_codes/c_convert_json_to_csv.py --json data.json
python report_script/utility_codes/d_export_file_to_azure.py --file data.csv --container esh --folder sanity_data/uploads
python report_script/utility_codes/d_export_file_to_azure.py --list-containers
python report_script/utility_codes/d_export_file_to_azure.py --list-folders --container knc
```
