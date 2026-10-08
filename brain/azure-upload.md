# Azure Upload utility

Upload any local CSV / Parquet / Excel (also TSV, TXT, JSON) into client Azure containers.

## Portal

**Data → Azure Upload** (`/data/azure-upload`)

1. Choose file  
2. Pick container key: **esh** / **knc** / **emm**  
3. Pick or type blob folder (lists existing prefixes under the container)  
4. Keep original name+extension **or** set a custom name  

Report registry code: `d_export_file_to_azure` (stage `utility_codes`).

## Script

`report_script/utility_codes/d_export_file_to_azure.py`

Shared helpers used by CLI and FastAPI (`backend/api/azure_export.py`).
