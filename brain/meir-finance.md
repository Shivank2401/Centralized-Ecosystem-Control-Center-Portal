# MEIR Finance (Closing Stock)

Module: `report_script.finance.a_meir_finance_report`  
Notebook source: `report_script/finance/a_MEIR_Finance.ipynb`

## Purpose
Build month-end MEIR Inventory Reconciles + Closing Stock Analyzer for ESH.
Processing / cleaning / ageing logic matches the notebook; only file selection
is parameterized by **report month**.

## Select report month
Interactive prompt (local CLI with a TTY), or:
```text
python report_script/finance/a_meir_finance_report.py --month Nov --year 2025
python report_script/finance/a_meir_finance_report.py --report-month Nov-2025
python report_script/finance/a_meir_finance_report.py --report-month Nov-2025 --dry-run
```

**Portal / pipeline worker (no stdin):** uses the previous calendar month automatically.
Override with env `MEIR_REPORT_MONTH=Nov-2025` (or pass `month=` / `year=` / `report_month=` into `run()`).

Pipeline: Stage **finance** → MEIR Finance (Closing Stock).

## Source file rules (example: Nov-2025)
| Channel | Folder | Filename date |
|---------|--------|----------------|
| Flipkart / EasyEcom | Nov-2025 | 30-Nov-2025 |
| Walmart | Dec-2025 | 30-Nov-2025 (fallback 01-Dec) |
| 3G | Dec-2025 | 30-Nov-2025 |
| Shipcube | Dec-2025 | 01-Dec-2025 (Date col = 30-Nov-2025) |
| Updike | Dec-2025 | 30-Nov-2025 |
| Amazon US / CA | Dec-2025 | 01-Dec-2025 |
| Amazon other geos | Nov-2025 | 30-Nov-2025 |

At start of each run the script prints every selected **file name** + full path.

Inventory root: `ESH_DATA_ROOT` from `.env`.

## Outputs
- `{ESH_DATA_ROOT}/Output_Database/Inventory Reconciles/{next_year}/{next}/Inventory Reconciles_{01-next}.xlsx`
- `{ESH_DATA_ROOT}/Output_Database/Closing Stock Analysis/Closing Stock Analyzer-{report}.xlsx`
