# Utility codes

Modules under `report_script/utility_codes/`.

Standalone helpers (not part of the standard inventory dataset). Available via
`run_pipeline.py` → **Stage: utility_codes**.

| Script | Purpose |
|--------|---------|
| `a_import_any_file_to_mysql.py` | Import CSV/Excel → MySQL table (snake_case columns) |
| `b_check_duplicate_image.py` | Export unique image basenames from a folder → CSV |
| `c_convert_json_to_csv.py` | Flatten JSON → CSV |

## MySQL credentials
Set in `.env` (see `.env.example`):
- `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD` (**required**), `MYSQL_DATABASE`
- Optional: `MYSQL_POOL_NAME`, `MYSQL_POOL_SIZE`

## Image export knobs
- `UTILITY_IMAGE_FOLDER` / `--folder`
- `UTILITY_IMAGE_OUTPUT` / `--output` (default `image_list.csv` in cwd)

## Run
```bash
python report_script/utility_codes/a_import_any_file_to_mysql.py --file data.csv --table my_table
python report_script/utility_codes/b_check_duplicate_image.py --folder "D:/imgs"
python report_script/utility_codes/c_convert_json_to_csv.py --json data.json
```
