# Pipeline stages

## Stage 1 — saving_reports
Module: `report_script.other_scripts.saving_raw_file_on_date`
`run(client=, geos=)` uses `ESH_DATA_ROOT` (or `INVENTORY_BASE`) as inventory root.

## Stage 2 — common (standard dataset)
Each script exposes `run(client=, geos=)` for `run_pipeline.py`.
Configs resolve `data_root` / `cogs_path` from `.env` via `config_manager.layouts`.

| Report key | Script | Output |
|------------|--------|--------|
| manage_fba | `amazon_reports.manage_fba_report` | `sanity_data/{CLIENT}/manage_fba/` |
| reserved | `amazon_reports.reserved_report` | `sanity_data/{CLIENT}/reserved/` |
| ageing | `amazon_reports.ageing_report` | `sanity_data/{CLIENT}/ageing/` |
| ledger | `amazon_reports.ledger_report` | `sanity_data/{CLIENT}/ledger/` |
| order | `amazon_reports.orders_report` | `sanity_data/{CLIENT}/orders/` |
| shopify_orders | `shopify_reports.orders_report` | `sanity_data/KNC/orders/{GEO}_shopify_orders_database.*` |
| inventory_database | `amazon_reports.inventory_database` | `sanity_data/{CLIENT}/inventory_database/` |
| item_master | `item_master.item_master_manager` | Azure + local `item_master/` cache |
| a_meir_finance | `finance.a_meir_finance_report` | Inventory Reconciles + Closing Stock Analyzer |
| esh_cogs | `want_to_update.esh_cogs` | Azure `thrive-client-ecosoulhome/cogs/` (Excel → blob) |
| knc_cogs | `want_to_update.knc_cogs` | Azure `thrive-client-kinetica/cogs/` (Excel → blob) |
| d_download_cogs | `supply_chain.d_download_cogs` | `cogs/{esh\|knc}/` from Azure |
| pincode | `want_to_update.pincode` | `pincode/{cc}_amazon_pincode.csv` (+ Azure) |
| invalid_skus | `want_to_update.invalid_skus` | `config_manager/invalid_skus.json` (view/add per client) |

## Stage — utility_codes
Standalone helpers (interactive / CLI). See `brain/utility-codes.md`.

| Report key | Script |
|------------|--------|
| a_import_any_file_to_mysql | `utility_codes.a_import_any_file_to_mysql` |
| b_check_duplicate_image | `utility_codes.b_check_duplicate_image` |
| c_convert_json_to_csv | `utility_codes.c_convert_json_to_csv` |

See also: `brain/item-master.md`, `brain/meir-finance.md`, `brain/cogs.md`, `brain/pincode.md`, `brain/invalid-skus.md`, `brain/inventory-database.md`, `brain/common-run-logs.md`.

## Stage 3 — requirement specific
| Key | Script | Output |
|-----|--------|--------|
| vector_report_amazon | `requirement_specific.vector_report_amazon` | `sanity_data/{CLIENT}/vector_report_amazon/{geo}_{platform}_inventory_report.parquet` (+ `.csv`) |
| vector_report_shopify | `requirement_specific.vector_report_shopify` | `sanity_data/KNC/vector_report/{geo}_shopify_inventory_report.parquet` (+ `.csv`) |
| emami_report | `requirement_specific.emami_report` | `sanity_data/EMM/{inventory,ads,orders,…}/` + Excel; Azure upload prompted |
| d_inventory_supply_chain | `requirement_specific.SC_inventory` | ESH inventory supply chain / instock (paths via `.env`; SKU clean via `esh_sku_cleaning`; ESH-only) |
| pnl_report | `atros_code.pnl_report` | `sanity_data/KNC/pnl/` |
| ad_sales_report | `atros_code.ad_sales_report` | `sanity_data/KNC/ads/` |
| decomposition_chart | `atros_code.decomposition_chart` | `sanity_data/KNC/decomposition_chart/` |
| total_inventory | not wired yet | — |
| city_state_orders | not wired yet (uses `orders_pincode.py` + `PINCODE_DATA_DIR`) | — |

See also: `brain/vector-datahive.md`, `brain/vector-datahive-shopify.md`.

## Stage 4 — sequence
Runs stages 1 → 2 → 3 in order.

## Dependency note
Common reports use `config_manager.report_helpers` (LoadStats, merge, column helpers).
After the final dataframe is built (including merge with existing outputs), each common sanity report runs `new_sku_check.check_final_dataframe_new_skus`: per client/geo, SKUs in the export frame vs the `sku` column of `cogs/{client}/{geo}_amazon_cogs`.

No dependency on `ecosoul.manage_fba_database`.
