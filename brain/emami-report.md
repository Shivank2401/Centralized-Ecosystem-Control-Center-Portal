# Emami UAE report

Module: `report_script.requirement_specific.emami_report`

Notebook source: `report_script/requirement_specific/emami_uae_code.ipynb` (reference).

Client: **EMM** (AE only). Builds multi-channel inventory / revenue / marketing / BuyBox from the Emami input tree (Amazon Vendor Central + Noon + Noon Minutes).

## Env

| Var | Required | Purpose |
|-----|----------|---------|
| `EMAMI_DATA_ROOT` | yes | Emami client DB root (`…/Emami`) with `input/amazon|noon|noon_minutes/uae/…` |
| `EMAMI_OUTPUT_ROOT` | no | Default: `sanity_data/EMM` (masters under `{report}/`) |
| `EMAMI_HELPER_FILE` | no | Default: `{EMAMI_DATA_ROOT}/input/helper_file/Emami (UAE)- Item Master Sheet.xlsx` |
| `PROCESS_YEAR` | no | Default: current calendar year |
| `AZURE_STORAGE_CONNECTION_STRING` or `EMAMI_AZURE_CONNECTION_STRING` | for Azure upload | Blob credentials |
| `CONTAINER_NAME_EMAMI` | no | Default: `thrive-client-emami` |

## Run

```bash
python report_script/requirement_specific/emami_report.py --year 2026
# after local save → interactive yes/no for Azure

python report_script/requirement_specific/emami_report.py --year 2026 --upload-azure
python report_script/requirement_specific/emami_report.py --year 2026 --skip-azure
# or: run_pipeline.py → client EMM → Requirement Specific → Emami UAE Report
```

## Outputs

Local (always saved before Azure prompt):

```
sanity_data/EMM/emami_report/inventory_output_{year}.xlsx   # + revenue / marketing / buybox
sanity_data/EMM/inventory/amazon_inventory.csv
sanity_data/EMM/inventory/noon_inventory.csv
sanity_data/EMM/ads/...
sanity_data/EMM/orders/...
sanity_data/EMM/buy_box/amazon_buybox.csv
sanity_data/EMM/product_pricing/noon_minutes_pricing.csv
```

Azure (optional, after yes / `--upload-azure`): same 11 CSVs under container `thrive-client-emami` at `sanity_data/{inventory|ads|orders|…}/`.

## Intentionally omitted from notebook

- Selenium Amazon BuyBox scraper (use historical files under `output/emami_amazon_buybox/`)
- Selenium Noon Minutes pricing scraper (`noon_minutes_pricing` upload skipped when empty)
- Diagnostic / test CSV dump cells
- Hardcoded OneDrive paths and Azure AccountKey (moved to `.env`)
