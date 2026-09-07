"""Emami UAE multi-channel reporting.

Builds inventory, revenue, marketing, and BuyBox datasets for Amazon Vendor
Central, Noon, and Noon Minutes from the Emami input tree.

Local masters are always written under ``sanity_data/EMM/{report}/`` (or
``EMAMI_OUTPUT_ROOT``), then the user is prompted yes/no before Azure CSV sync
(same pattern as Walmart Scintilla). Use ``--upload-azure`` / ``--skip-azure``
to skip the prompt.

Required environment:
    EMAMI_DATA_ROOT

Optional environment:
    EMAMI_OUTPUT_ROOT          # default: sanity_data/EMM
    EMAMI_HELPER_FILE
    PROCESS_YEAR
    AZURE_STORAGE_CONNECTION_STRING or EMAMI_AZURE_CONNECTION_STRING
    CONTAINER_NAME_EMAMI (default: thrive-client-emami)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import paths as cfg_paths
from config_manager.layouts import client_identity

_CLIENT = client_identity("EMM")
CLIENT_ID = _CLIENT["client_id"]
CLIENT_CODE = _CLIENT["client_code"]
COUNTRY = "AE"
EXCEL_SUBDIR = "emami_report"
DEFAULT_CONTAINER = "thrive-client-emami"

MONTH_ALIASES = {
    "jan": ["jan", "january"],
    "feb": ["feb", "february"],
    "mar": ["mar", "march"],
    "apr": ["apr", "april"],
    "may": ["may"],
    "jun": ["jun", "june"],
    "jul": ["jul", "july"],
    "aug": ["aug", "august"],
    "sep": ["sep", "sept", "september"],
    "oct": ["oct", "october"],
    "nov": ["nov", "november"],
    "dec": ["dec", "december"],
}

# Azure blob path (under container) AND local relative path under sanity_data/EMM/
AZURE_BLOB_KEYS = {
    "amazon_inventory": "sanity_data/inventory/amazon_inventory.csv",
    "amazon_ads": "sanity_data/ads/amazon_ads.csv",
    "amazon_orders": "sanity_data/orders/amazon_orders.csv",
    "amazon_buybox": "sanity_data/buy_box/amazon_buybox.csv",
    "noon_ads": "sanity_data/ads/noon_ads.csv",
    "noon_inventory": "sanity_data/inventory/noon_inventory.csv",
    "noon_revenue": "sanity_data/orders/noon_revenue.csv",
    "noon_minutes_ads": "sanity_data/ads/noon_minutes_ads.csv",
    "noon_minutes_inventory": "sanity_data/inventory/noon_minutes_inventory.csv",
    "noon_minutes_revenue": "sanity_data/orders/noon_minutes_revenue.csv",
    "noon_minutes_pricing": "sanity_data/product_pricing/noon_minutes_pricing.csv",
}


def _clean_env(name: str) -> str:
    return str(os.getenv(name, "")).strip().strip('"').strip("'")


def clean_asin(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.upper()
        .str.strip()
        .str.replace(".0", "", regex=False)
    )


def clean_date(series: pd.Series) -> pd.Series:
    # dayfirst=True: DD/MM/YYYY (UAE) does not flip to US month-first
    return pd.to_datetime(series, dayfirst=True, errors="coerce").dt.normalize()


@dataclass(frozen=True)
class EmamiConfig:
    """Resolved filesystem and runtime settings for one Emami report run."""

    base: Path
    output_folder: Path  # sanity_data/EMM (local client root)
    helper_file: Path
    year: int

    @property
    def excel_folder(self) -> Path:
        """Combined Excel workbooks: inventory / revenue / marketing / buybox."""
        return self.output_folder / EXCEL_SUBDIR

    def local_master_path(self, blob_path: str) -> Path:
        """
        Map Azure blob ``sanity_data/inventory/foo.csv`` →
        ``{output_folder}/inventory/foo.csv``.
        """
        rel = blob_path.replace("\\", "/").lstrip("/")
        if rel.startswith("sanity_data/"):
            rel = rel[len("sanity_data/") :]
        return self.output_folder / Path(rel)

    @property
    def amazon_inventory_root(self) -> Path:
        return self.base / "input" / "amazon" / "uae" / "inventory" / str(self.year)

    @property
    def amazon_revenue_root(self) -> Path:
        return self.base / "input" / "amazon" / "uae" / "revenue" / str(self.year)

    @property
    def amazon_marketing_root(self) -> Path:
        return self.base / "input" / "amazon" / "uae" / "marketing" / str(self.year)

    @property
    def noon_inventory_root(self) -> Path:
        return self.base / "input" / "noon" / "uae" / "inventory" / str(self.year)

    @property
    def noon_revenue_root(self) -> Path:
        return self.base / "input" / "noon" / "uae" / "revenue" / str(self.year)

    @property
    def noon_marketing_root(self) -> Path:
        return self.base / "input" / "noon" / "uae" / "marketing" / str(self.year)

    @property
    def nms_inventory_root(self) -> Path:
        return self.base / "input" / "noon_minutes" / "uae" / "inventory" / str(self.year)

    @property
    def nms_revenue_root(self) -> Path:
        return self.base / "input" / "noon_minutes" / "uae" / "revenue" / str(self.year)

    @property
    def nms_marketing_root(self) -> Path:
        return self.base / "input" / "noon_minutes" / "uae" / "marketing" / str(self.year)

    @property
    def buybox_history_root(self) -> Path:
        return self.base / "output" / "emami_amazon_buybox" / str(self.year) / "emami" / "ae"


def get_emami_config(year: int | None = None) -> EmamiConfig:
    """Resolve Emami paths from environment and validate the process year."""
    base = cfg_paths.env_path("EMAMI_DATA_ROOT")
    if base is None:
        raise EnvironmentError("EMAMI_DATA_ROOT is required.")
    resolved_year = int(year or _clean_env("PROCESS_YEAR") or datetime.now().year)
    if resolved_year < 2000 or resolved_year > 2100:
        raise ValueError(f"Invalid report year: {resolved_year}")
    output_override = cfg_paths.env_path("EMAMI_OUTPUT_ROOT", required=False)
    # Local masters: sanity_data/EMM/{inventory|ads|orders|buy_box|…}
    output = output_override or (cfg_paths.sanity_data_root() / CLIENT_CODE)
    helper_override = cfg_paths.env_path("EMAMI_HELPER_FILE", required=False)
    helper = helper_override or (
        base / "input" / "helper_file" / "Emami (UAE)- Item Master Sheet.xlsx"
    )
    return EmamiConfig(
        base=base,
        output_folder=output,
        helper_file=helper,
        year=resolved_year,
    )


def _build_report_frames(config: EmamiConfig) -> dict[str, pd.DataFrame]:
    """Execute the scrubbed notebook production spine using resolved paths."""
    BASE = str(config.base)
    YEAR = config.year
    MONTHS = MONTH_ALIASES.copy()
    AMZ_INV_ROOT = str(config.amazon_inventory_root)
    AMZ_REV_ROOT = str(config.amazon_revenue_root)
    AMZ_ADS_ROOT = str(config.amazon_marketing_root)
    NOON_INV_ROOT = str(config.noon_inventory_root)
    NOON_REV_ROOT = str(config.noon_revenue_root)
    NOON_ADS_ROOT = str(config.noon_marketing_root)
    NMS_INV_ROOT = str(config.nms_inventory_root)
    NMS_REV_ROOT = str(config.nms_revenue_root)
    NMS_ADS_ROOT = str(config.nms_marketing_root)
    HELPER_FILE = str(config.helper_file)
    import warnings
    warnings.filterwarnings('ignore', message='Workbook contains no default style')
    amz_inventory_parts = []
    for month_key, month_aliases in MONTHS.items():
        input_folder = None
        folder_name = None
        for alias in month_aliases:
            candidate = os.path.join(AMZ_INV_ROOT, alias)
            if os.path.exists(candidate):
                input_folder = candidate
                folder_name = alias
                break
        if input_folder is None:
            continue
        output_folder = os.path.join(AMZ_INV_ROOT, f'{folder_name}_merged')
        os.makedirs(output_folder, exist_ok=True)
        month_data = []
        for file in sorted(os.listdir(input_folder)):
            file_lower = file.lower()
            if not (file_lower.endswith('.xlsx') or file_lower.endswith('.csv')):
                continue
            if 'amazon_emami_inventory' not in file_lower:
                continue
            path = os.path.join(input_folder, file)
            try:
                if file_lower.endswith('.csv'):
                    try:
                        df = pd.read_csv(path, skiprows=1, dtype=str, encoding='utf-8-sig', encoding_errors='ignore', on_bad_lines='skip')
                        df.columns = df.columns.astype(str).str.strip()
                        if 'ASIN' not in df.columns:
                            raise ValueError('ASIN not in columns after skiprows=1')
                    except Exception:
                        raw = pd.read_csv(path, header=None, dtype=str, encoding='utf-8-sig', encoding_errors='ignore', engine='python', sep=',', on_bad_lines='skip')
                        found = False
                        for _ri in range(min(10, len(raw))):
                            if 'ASIN' in raw.iloc[_ri].astype(str).values:
                                df = pd.read_csv(path, skiprows=_ri, dtype=str, encoding='utf-8-sig', encoding_errors='ignore', on_bad_lines='skip')
                                df.columns = df.columns.astype(str).str.strip()
                                found = True
                                break
                        if not found:
                            raise ValueError('ASIN header row not found in CSV')
                else:
                    raw = pd.read_excel(path, header=None)
                    header_matches = raw.eq('ASIN').any(axis=1)
                    if not header_matches.any():
                        raise ValueError('ASIN header row not found')
                    header_row = header_matches[header_matches].index[0]
                    df = pd.read_excel(path, skiprows=header_row, dtype=str)
                df.columns = df.columns.astype(str).str.strip()
                match = re.search('(\\d{1,2})_(\\w+)_(\\d{4})', file.lower())
                if match:
                    day = match.group(1)
                    month = match.group(2)
                    year = match.group(3)
                    file_date = pd.to_datetime(f'{day}_{month}_{year}', format='%d_%b_%Y', errors='coerce')
                    if pd.isna(file_date):
                        file_date = pd.to_datetime(f'{day}_{month}_{year}', format='%d_%B_%Y', errors='coerce')
                    df['Date'] = file_date
                else:
                    df['Date'] = pd.NaT
                if 'ASIN' in df.columns:
                    df['ASIN'] = clean_asin(df['ASIN'])
                df['Sales Channel'] = 'Vendor Central'
                df['source_file'] = file
                month_data.append(df)
            except Exception as e:
                pass
        if month_data:
            merged = pd.concat(month_data, ignore_index=True)
            merged['Date'] = clean_date(merged['Date'])
            if 'ASIN' in merged.columns:
                merged = merged[merged['ASIN'].notna()]
            sort_cols = ['Date']
            if 'ASIN' in merged.columns:
                sort_cols.append('ASIN')
            merged = merged.sort_values(sort_cols)
            merged = merged.drop_duplicates()
            out = os.path.join(output_folder, f'merged_output_inventory_{folder_name}_{YEAR}.xlsx')
            merged.to_excel(out, index=False)
            amz_inventory_parts.append(merged)
    if amz_inventory_parts:
        amz_inv_df = pd.concat(amz_inventory_parts, ignore_index=True)
        if 'ASIN' in amz_inv_df.columns:
            amz_inv_df['ASIN'] = clean_asin(amz_inv_df['ASIN'])
        amz_inv_df['Date'] = clean_date(amz_inv_df['Date'])
        sort_cols = ['Date']
        if 'ASIN' in amz_inv_df.columns:
            sort_cols.append('ASIN')
        amz_inv_df = amz_inv_df.sort_values(sort_cols)
    # Month folder tokens used by Noon / NMs / revenue / ads loaders
    MONTHS = list(MONTH_ALIASES.keys())
    nms_inventory_parts = []
    for process_month in MONTHS:
        month_folder = os.path.join(NMS_INV_ROOT, process_month)
        if not os.path.exists(month_folder):
            continue
        all_data = []
        for day_folder in sorted(os.listdir(month_folder)):
            day_path = os.path.join(month_folder, day_folder)
            if not os.path.isdir(day_path):
                continue
            for file in sorted(os.listdir(day_path)):
                if not file.lower().endswith(('.csv', '.xlsx')):
                    continue
                file_path = os.path.join(day_path, file)
                try:
                    if file.lower().endswith('.csv'):
                        df = pd.read_csv(file_path, dtype=str, encoding='utf-8-sig')
                    else:
                        df = pd.read_excel(file_path, dtype=str)
                    df.columns = df.columns.astype(str).str.strip()
                    match = re.search('(\\d{1,2})_([A-Za-z]+)_(\\d{4})', file)
                    if match:
                        file_date = pd.to_datetime(f'{match.group(1)}-{match.group(2)}-{match.group(3)}', errors='coerce')
                    else:
                        file_date = pd.NaT
                    df['Date'] = file_date
                    df['source_file'] = file
                    df['Sales Channel'] = 'Noon Minutes'
                    all_data.append(df)
                except Exception as e:
                    pass
        if all_data:
            merged_df = pd.concat(all_data, ignore_index=True)
            merged_df['Date'] = pd.to_datetime(merged_df['Date'], errors='coerce')
            merged_df = merged_df.drop_duplicates()
            sort_cols = ['Date']
            if 'NIN' in merged_df.columns:
                sort_cols.append('NIN')
            merged_df = merged_df.sort_values(sort_cols)
            output_file = os.path.join(month_folder, f'merged_nms_{process_month}_{YEAR}.xlsx')
            merged_df.to_excel(output_file, index=False)
            nms_inventory_parts.append(merged_df)
    if nms_inventory_parts:
        nms_inv_df = pd.concat(nms_inventory_parts, ignore_index=True)
        nms_inv_df['Date'] = pd.to_datetime(nms_inv_df['Date'], errors='coerce')
        nms_inv_df = nms_inv_df.sort_values('Date')
    for process_month in MONTHS:
        month_folder = os.path.join(NOON_INV_ROOT, process_month)
        if not os.path.exists(month_folder):
            continue
        all_data = []
        for date_folder in sorted(os.listdir(month_folder)):
            date_path = os.path.join(month_folder, date_folder)
            if not os.path.isdir(date_path):
                continue
            for file in os.listdir(date_path):
                if not file.lower().endswith(('.csv', '.xlsx')):
                    continue
                file_path = os.path.join(date_path, file)
                try:
                    if file.lower().endswith('.csv'):
                        df = pd.read_csv(file_path, dtype=str)
                    else:
                        df = pd.read_excel(file_path, dtype=str)
                    match = re.search('(\\d{1,2})_([A-Za-z]+)_(\\d{4})', file)
                    if match:
                        file_date = pd.to_datetime(f'{match.group(1)}-{match.group(2)}-{match.group(3)}', errors='coerce')
                        df['Date'] = file_date
                    df['source_file'] = file
                    all_data.append(df)
                except Exception as e:
                    pass
        if all_data:
            merged_df = pd.concat(all_data, ignore_index=True)
            output_file = os.path.join(month_folder, f'merged_noon_{process_month}_{YEAR}.xlsx')
            merged_df.to_excel(output_file, index=False)
    inv_parts = []
    for month in MONTHS:
        file_path = os.path.join(AMZ_INV_ROOT, f'{month}_merged', f'merged_output_inventory_{month}_{YEAR}.xlsx')
        if os.path.exists(file_path):
            try:
                df = pd.read_excel(file_path)
                df['processed_month'] = month
                inv_parts.append(df)
            except Exception as e:
                pass
    if inv_parts:
        amz_inv_df = pd.concat(inv_parts, ignore_index=True)
    else:
        amz_inv_df = pd.DataFrame()
    amz_inv_df.columns = amz_inv_df.columns.astype(str).str.strip()
    amz_inv_df.drop(columns=['Product Title'], errors='ignore', inplace=True)
    amz_inv_df.rename(columns={'Sellable On Hand Units': 'Available Inventory', 'Sellable On Hand Inventory': 'Sellable Inventory Amount', 'Open Purchase Order Quantity': 'Open POs', 'Net Received': 'PO_received_amount', 'Net Received Units': 'PO_received_Units', 'Receive Fill %': 'Receive_Fill_Rate', 'Unsellable On Hand Inventory': 'Unsellable On Hand Inventory Amount', 'Subcategory': 'Product Sub Category'}, inplace=True)
    amz_inv_df['ASIN'] = amz_inv_df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
    amz_inv_df['Date'] = pd.to_datetime(amz_inv_df['Date'], errors='coerce').dt.normalize()
    amz_inv_df['Sales Channel'] = 'Vendor Central'
    inventory_numeric_cols = ['Available Inventory', 'Sellable Inventory Amount', 'Open POs', 'PO_received_amount', 'PO_received_Units', 'Receive_Fill_Rate', 'Unsellable On Hand Inventory Amount']
    for col in inventory_numeric_cols:
        if col in amz_inv_df.columns:
            amz_inv_df[col] = amz_inv_df[col].astype(str).str.replace(',', '', regex=False).str.replace('%', '', regex=False).str.strip().pipe(pd.to_numeric, errors='coerce').fillna(0)
    if 'Available Inventory' in amz_inv_df.columns:
        amz_inv_df['Available Inventory'] = amz_inv_df['Available Inventory'].astype(int)
    amz_inv_df = amz_inv_df.drop_duplicates(subset=['ASIN', 'Date'], keep='last')
    amz_inv_df = amz_inv_df.sort_values(['ASIN', 'Date'])
    amz_inv_df['year_month'] = amz_inv_df['Date'].dt.to_period('M')
    amz_inv_df['in_stock_flag'] = (amz_inv_df['Available Inventory'] > 0).astype(int)
    amz_inv_df['cumulative_instock_days'] = amz_inv_df.groupby(['ASIN', 'year_month'])['in_stock_flag'].cumsum()
    amz_inv_df['day_of_month'] = amz_inv_df['Date'].dt.day
    amz_inv_df['Instock Rate'] = (amz_inv_df['cumulative_instock_days'] / amz_inv_df['day_of_month'] * 100).round(2)
    amz_inv_df.drop(columns=['year_month'], inplace=True)
    raw_helper = pd.read_excel(HELPER_FILE, header=None)
    header_row = None
    possible_headers = ['Brand', 'Amazon ASIN', 'Amazon ASIN\n(Vendor Central)', 'Product Code\n(Noon Minutes)', 'Product Code\n(Noon Core)']
    for i in range(len(raw_helper)):
        row_values = raw_helper.iloc[i].astype(str).str.strip().tolist()
        if any((h in row_values for h in possible_headers)):
            header_row = i
            break
    if header_row is not None:
        helper_df = pd.read_excel(HELPER_FILE, skiprows=header_row)
    else:
        helper_df = pd.read_excel(HELPER_FILE)
    helper_df.columns = helper_df.columns.astype(str).str.strip()
    amazon_helper_col = None
    possible_amz_cols = ['Amazon ASIN\n(Vendor Central)', 'Amazon ASIN (Vendor Central)', 'Amazon ASIN']
    for col in helper_df.columns:
        if str(col).strip() in possible_amz_cols:
            amazon_helper_col = col
            break
    if amazon_helper_col:
        helper_df.rename(columns={amazon_helper_col: 'ASIN'}, inplace=True)
    else:
        helper_df['ASIN'] = np.nan
    helper_df['ASIN'] = helper_df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
    helper_df.rename(columns={'Category': 'Product Category', 'Product Type': 'Product Sub Category', 'Product Description': 'Product Name', 'Size': 'Pack Size'}, inplace=True)
    helper_cols = ['ASIN', 'Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size', 'VC Ideal Price']
    available_helper_cols = [c for c in helper_cols if c in helper_df.columns]
    helper_df = helper_df[available_helper_cols]
    helper_df = helper_df[helper_df['ASIN'].notna()]
    helper_df = helper_df[helper_df['ASIN'] != '']
    helper_df = helper_df.drop_duplicates(subset=['ASIN'])

    def clean_merge_asin(series):
        return series.astype(str).str.upper().str.strip().str.replace('\xa0', '', regex=False).str.replace('.0', '', regex=False).str.replace('\\s+', '', regex=True)
    amz_inv_df['ASIN'] = clean_merge_asin(amz_inv_df['ASIN'])
    helper_df['ASIN'] = clean_merge_asin(helper_df['ASIN'])
    helper_df = helper_df[helper_df['ASIN'].notna()]
    helper_df = helper_df[helper_df['ASIN'] != '']
    helper_df = helper_df.drop_duplicates(subset=['ASIN'], keep='first')
    inventory_asins = set(amz_inv_df['ASIN'].dropna().unique())
    helper_asins = set(helper_df['ASIN'].dropna().unique())
    matched_asins = inventory_asins & helper_asins
    amz_inv_df = amz_inv_df.merge(helper_df, on='ASIN', how='left', suffixes=('', '_helper'))
    metadata_cols = ['Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size', 'VC Ideal Price']
    for col in metadata_cols:
        helper_col = f'{col}_helper'
        if col not in amz_inv_df.columns:
            amz_inv_df[col] = np.nan
        if helper_col in amz_inv_df.columns:
            amz_inv_df[col] = np.where(amz_inv_df[helper_col].notna(), amz_inv_df[helper_col], amz_inv_df[col])
            amz_inv_df.drop(columns=[helper_col], inplace=True)
    for col in metadata_cols:
        if col in amz_inv_df.columns:
            amz_inv_df[col] = amz_inv_df[col].astype(str).replace('nan', np.nan).replace('None', np.nan).replace('', np.nan).fillna('Unknown')
    drop_cols = [c for c in amz_inv_df.columns if c.endswith('_x') or c.endswith('_y')]
    if drop_cols:
        amz_inv_df.drop(columns=drop_cols, inplace=True)
    for col in metadata_cols:
        if col in amz_inv_df.columns:
            pass
    TEST_ASIN = 'B0G64MSXJS'
    if TEST_ASIN in amz_inv_df['ASIN'].values:
        pass
    metadata_cols = ['Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size', 'VC Ideal Price']
    for col in metadata_cols:
        helper_col = f'{col}_helper'
        if helper_col in amz_inv_df.columns:
            amz_inv_df[col] = amz_inv_df[helper_col].combine_first(amz_inv_df.get(col))
            amz_inv_df[col] = amz_inv_df[col].replace('', np.nan).replace('nan', np.nan).replace('None', np.nan).fillna('Unknown')
            amz_inv_df.drop(columns=[helper_col], inplace=True)
    for col in metadata_cols:
        if col in amz_inv_df.columns:
            amz_inv_df[col] = amz_inv_df[col].fillna('Unknown')
    drop_cols = [c for c in amz_inv_df.columns if c.endswith('_x') or c.endswith('_y')]
    if drop_cols:
        amz_inv_df.drop(columns=drop_cols, inplace=True)
    if 'Brand' in amz_inv_df.columns:
        pass
    amz_revenue_parts = []
    for process_month in MONTHS:
        input_folder = os.path.join(AMZ_REV_ROOT, process_month)
        output_folder = os.path.join(AMZ_REV_ROOT, f'{process_month}_output')
        os.makedirs(output_folder, exist_ok=True)
        if not os.path.exists(input_folder):
            continue
        month_data = []
        for file in sorted(os.listdir(input_folder)):
            file_lower = file.lower()
            if file.startswith('~$'):
                continue
            if not (file_lower.endswith('.xlsx') or file_lower.endswith('.csv')):
                continue
            if 'sales_amazon_emami' not in file_lower:
                continue
            path = os.path.join(input_folder, file)
            try:
                if file_lower.endswith('.csv'):
                    try:
                        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig', encoding_errors='ignore', on_bad_lines='skip')
                        df.columns = df.columns.astype(str).str.strip()
                        if 'ASIN' not in df.columns:
                            raise ValueError('ASIN not in columns')
                    except Exception:
                        raw = pd.read_csv(path, header=None, dtype=str, encoding='utf-8-sig', encoding_errors='ignore', engine='python', sep=',', on_bad_lines='skip')
                        found = False
                        for _ri in range(min(10, len(raw))):
                            if 'ASIN' in raw.iloc[_ri].astype(str).values:
                                df = pd.read_csv(path, skiprows=_ri, dtype=str, encoding='utf-8-sig', encoding_errors='ignore', on_bad_lines='skip')
                                df.columns = df.columns.astype(str).str.strip()
                                found = True
                                break
                        if not found:
                            raise ValueError('ASIN header row not found in CSV')
                else:
                    raw = pd.read_excel(path, header=None)
                    header_matches = raw.eq('ASIN').any(axis=1)
                    if not header_matches.any():
                        raise ValueError('ASIN header row not found')
                    header_row = header_matches[header_matches].index[0]
                    df = pd.read_excel(path, skiprows=header_row, dtype=str)
                df.columns = df.columns.astype(str).str.strip()
                match = re.search('(\\d{1,2})_(\\w+)_(\\d{4})', file.lower())
                if match:
                    day = match.group(1)
                    month = match.group(2)
                    year = match.group(3)
                    file_date = pd.to_datetime(f'{day}_{month}_{year}', format='%d_%b_%Y', errors='coerce')
                    if pd.isna(file_date):
                        file_date = pd.to_datetime(f'{day}_{month}_{year}', format='%d_%B_%Y', errors='coerce')
                    df['Date'] = file_date
                else:
                    df['Date'] = pd.NaT
                if 'ASIN' in df.columns:
                    df['ASIN'] = clean_asin(df['ASIN'])
                df['Sales Channel'] = 'Vendor Central'
                df['source_file'] = file
                month_data.append(df)
            except Exception as e:
                pass
        if month_data:
            merged = pd.concat(month_data, ignore_index=True)
            merged['Date'] = clean_date(merged['Date'])
            if 'ASIN' in merged.columns:
                merged = merged[merged['ASIN'].notna()]
            sort_cols = ['Date']
            if 'ASIN' in merged.columns:
                sort_cols.append('ASIN')
            merged = merged.sort_values(sort_cols)
            merged = merged.drop_duplicates()
            out = os.path.join(output_folder, f'merged_revenue_{process_month}_{YEAR}.xlsx')
            merged.to_excel(out, index=False)
            amz_revenue_parts.append(merged)
    if amz_revenue_parts:
        pass
    rev_parts = []
    for month in MONTHS:
        file_path = os.path.join(AMZ_REV_ROOT, f'{month}_output', f'merged_revenue_{month}_{YEAR}.xlsx')
        if os.path.exists(file_path):
            try:
                df = pd.read_excel(file_path)
                df['processed_month'] = month
                rev_parts.append(df)
            except Exception as e:
                pass
    if rev_parts:
        amz_rev_df = pd.concat(rev_parts, ignore_index=True)
    else:
        amz_rev_df = pd.DataFrame()
    amz_rev_df.columns = amz_rev_df.columns.astype(str).str.strip()
    amz_rev_df.drop(columns=['Product Title'], errors='ignore', inplace=True)
    amz_rev_df.rename(columns={'Shipped Revenue': 'total_sales', 'Shipped Units': 'total_units'}, inplace=True)
    amz_rev_df['ASIN'] = amz_rev_df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
    amz_rev_df['Date'] = pd.to_datetime(amz_rev_df['Date'], dayfirst=True, errors='coerce').dt.normalize()
    if 'total_sales' in amz_rev_df.columns:
        amz_rev_df['total_sales'] = amz_rev_df['total_sales'].astype(str).str.replace('AED', '', regex=False).str.replace(',', '', regex=False).str.strip().pipe(pd.to_numeric, errors='coerce').fillna(0)
    if 'total_units' in amz_rev_df.columns:
        amz_rev_df['total_units'] = pd.to_numeric(amz_rev_df['total_units'], errors='coerce').fillna(0).astype(int)
    amz_rev_df['Sales Channel'] = 'Vendor Central'
    amz_rev_df = amz_rev_df.groupby(['ASIN', 'Date'], as_index=False).agg({'total_sales': 'sum', 'total_units': 'sum'})
    amz_rev_df['Sales Channel'] = 'Vendor Central'
    amz_rev_df = amz_rev_df.sort_values(['ASIN', 'Date'])
    amz_rev_df = amz_rev_df.merge(helper_df, on='ASIN', how='left', suffixes=('', '_helper'))
    metadata_cols = ['Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size', 'VC Ideal Price']
    for col in metadata_cols:
        helper_col = f'{col}_helper'
        if helper_col in amz_rev_df.columns:
            amz_rev_df[col] = amz_rev_df[helper_col].combine_first(amz_rev_df.get(col))
            amz_rev_df[col] = amz_rev_df[col].replace('', np.nan).replace('nan', np.nan).replace('None', np.nan).fillna('Unknown')
            amz_rev_df.drop(columns=[helper_col], inplace=True)
    for col in metadata_cols:
        helper_col = f'{col}_helper'
        if helper_col in amz_rev_df.columns:
            if col not in amz_rev_df.columns:
                amz_rev_df[col] = np.nan
            amz_rev_df[col] = amz_rev_df[col].replace('Unknown', np.nan).replace('', np.nan).replace('nan', np.nan)
            amz_rev_df[col] = amz_rev_df[col].fillna(amz_rev_df[helper_col])
            amz_rev_df.drop(columns=[helper_col], inplace=True)
    if 'Brand' in amz_rev_df.columns:
        pass

    def _clean_money(series):
        return series.astype(str).str.replace(',', '', regex=False).str.replace('%', '', regex=False).str.replace('AED', '', regex=False).str.strip().pipe(pd.to_numeric, errors='coerce').fillna(0)

    def _rename_ads_cols(df):
        """One canonical rename map, applied identically to SP and SD."""
        df = df.copy()
        df.columns = df.columns.astype(str).str.strip()
        df.rename(columns={'Advertised ASIN': 'ASIN', '14 Day Total Sales ': 'ads_sales', '14 Day Total Sales': 'ads_sales', '14 Day Total Units (#)': 'ads_unit_sold', 'Spend': 'ads_spend', '14 Day Conversion Rate': 'CVR', 'Start Date': 'Date'}, inplace=True)
        if df.columns.duplicated().any():
            dup_names = df.columns[df.columns.duplicated()].unique().tolist()
            for name in dup_names:
                cols = df.loc[:, df.columns == name]
                coalesced = cols.bfill(axis=1).iloc[:, 0]
                df = df.loc[:, df.columns != name]
                df[name] = coalesced
        return df

    def _checksum(df, label, col='ads_sales'):
        total = pd.to_numeric(df.get(col, 0), errors='coerce').fillna(0).sum()
    spap_parts = []
    for month in MONTHS:
        file_path = os.path.join(AMZ_ADS_ROOT, month, f'sponsored_products_advertised_product_emami_{month}_{YEAR}.xlsx')
        if not os.path.exists(file_path):
            continue
        try:
            df = pd.read_excel(file_path)
            df = _rename_ads_cols(df)
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.normalize()
            df['ASIN'] = df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
            df['ads_sales'] = _clean_money(df['ads_sales']) if 'ads_sales' in df.columns else 0.0
            df['processed_month'] = month
            df['Sales Channel'] = 'Vendor Central'
            df['Campaign Type'] = 'SPAP'
            _checksum(df, f'SP raw file ({month})')
            spap_parts.append(df)
        except Exception as e:
            pass
    sd_parts = []
    for month in MONTHS:
        candidates = [f'Sponsored_Display_Advertised_product_emami_{month}_{YEAR}.xlsx', f'sponsored_display_advertised_product_emami_{month}_{YEAR}.xlsx']
        file_path = None
        for fname in candidates:
            p = os.path.join(AMZ_ADS_ROOT, month, fname)
            if os.path.exists(p):
                file_path = p
                break
        if file_path is None:
            continue
        try:
            df = pd.read_excel(file_path)
            df = _rename_ads_cols(df)
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.normalize()
            df['ASIN'] = df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
            df['ads_sales'] = _clean_money(df['ads_sales']) if 'ads_sales' in df.columns else 0.0
            df['processed_month'] = month
            df['Sales Channel'] = 'Vendor Central'
            df['Campaign Type'] = 'SD'
            _checksum(df, f'SD raw file ({month})')
            sd_parts.append(df)
        except Exception as e:
            pass
    all_amz_ads_parts = spap_parts + sd_parts
    if all_amz_ads_parts:
        amz_ads_df = pd.concat(all_amz_ads_parts, ignore_index=True)
        amz_ads_df.columns = amz_ads_df.columns.astype(str).str.strip()
        amz_ads_df = amz_ads_df.loc[:, ~amz_ads_df.columns.duplicated()]
        _checksum(amz_ads_df[amz_ads_df['Campaign Type'] == 'SPAP'], 'Combined - SPAP slice')
        _checksum(amz_ads_df[amz_ads_df['Campaign Type'] == 'SD'], 'Combined - SD slice')
    else:
        amz_ads_df = pd.DataFrame()
    numeric_cols = ['ads_sales', 'ads_unit_sold', 'ads_spend', 'Impressions', 'Clicks', 'Click-Thru Rate (CTR)', 'Cost Per Click (CPC)', 'Total Advertising Cost of Sales (ACOS)', 'Total Return on Advertising Spend (ROAS)', 'CVR']
    for col in numeric_cols:
        if col in amz_ads_df.columns:
            amz_ads_df[col] = _clean_money(amz_ads_df[col])
        else:
            amz_ads_df[col] = 0
    _checksum(amz_ads_df[amz_ads_df['Campaign Type'] == 'SD'], 'After numeric cleaning - SD')
    before_rows = len(amz_ads_df)
    amz_ads_df = amz_ads_df.drop_duplicates(subset=['ASIN', 'Date', 'Campaign Name', 'Ad Group Name', 'Campaign Type'], keep='last')
    if len(amz_ads_df) != before_rows:
        pass
    _checksum(amz_ads_df[amz_ads_df['Campaign Type'] == 'SD'], 'After dedup - SD')
    _checksum(amz_ads_df[amz_ads_df['Campaign Type'] == 'SPAP'], 'After dedup - SPAP')
    campaign_cols = ['ASIN', 'Date', 'Sales Channel', 'Campaign Name', 'Campaign Type', 'Portfolio name', 'Ad Group Name', 'ads_sales', 'ads_unit_sold', 'ads_spend', 'Impressions', 'Clicks', 'Click-Thru Rate (CTR)', 'Cost Per Click (CPC)', 'Total Advertising Cost of Sales (ACOS)', 'Total Return on Advertising Spend (ROAS)', 'CVR']
    campaign_cols = [c for c in campaign_cols if c in amz_ads_df.columns]
    amz_ads_campaign = amz_ads_df[campaign_cols].copy()
    _checksum(amz_ads_campaign[amz_ads_campaign['Campaign Type'] == 'SD'], 'amz_ads_campaign - SD')
    amz_ads_agg = amz_ads_df.groupby(['ASIN', 'Date', 'Sales Channel'], as_index=False).agg({'ads_sales': 'sum', 'ads_unit_sold': 'sum', 'ads_spend': 'sum', 'Impressions': 'sum', 'Clicks': 'sum'})
    _checksum(amz_ads_agg, 'amz_ads_agg (all types combined)')
    amz_ads_campaign = amz_ads_campaign.merge(helper_df, on='ASIN', how='left', suffixes=('', '_helper'))
    metadata_cols = ['Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size', 'VC Ideal Price']
    for col in metadata_cols:
        helper_col = f'{col}_helper'
        if helper_col in amz_ads_campaign.columns:
            if col not in amz_ads_campaign.columns:
                amz_ads_campaign[col] = np.nan
            amz_ads_campaign[col] = amz_ads_campaign[helper_col].combine_first(amz_ads_campaign[col])
            amz_ads_campaign[col] = amz_ads_campaign[col].replace(['', 'nan', 'None'], np.nan).fillna('Unknown')
            amz_ads_campaign.drop(columns=[helper_col], inplace=True)
    drop_cols = [c for c in amz_ads_campaign.columns if c.endswith('_x') or c.endswith('_y')]
    if drop_cols:
        amz_ads_campaign.drop(columns=drop_cols, inplace=True)
    _checksum(amz_ads_campaign[amz_ads_campaign['Campaign Type'] == 'SD'], 'FINAL amz_ads_campaign - SD')
    _checksum(amz_ads_campaign[amz_ads_campaign['Campaign Type'] == 'SPAP'], 'FINAL amz_ads_campaign - SPAP')
    if 'Brand' in amz_ads_campaign.columns:
        pass
    for month in MONTHS:
        input_folder = os.path.join(NOON_ADS_ROOT, month)
        output_folder = os.path.join(NOON_ADS_ROOT, f'{month}_output')
        if not os.path.exists(input_folder):
            continue
        os.makedirs(output_folder, exist_ok=True)
        all_data = []
        for file in sorted(os.listdir(input_folder)):
            if file.startswith('~$'):
                continue
            if not file.lower().endswith(('.xlsx', '.xls')):
                continue
            if 'ads_noon' not in file.lower():
                continue
            file_path = os.path.join(input_folder, file)
            try:
                df = pd.read_excel(file_path, sheet_name='(Product) Sku')
                df.columns = df.columns.astype(str).str.strip()
                match = re.search('(\\d{2})_(\\w+)_(\\d{4})', file.lower())
                if match:
                    day = match.group(1)
                    month_name = match.group(2)
                    year = match.group(3)
                    month_map = {'jan': 'Jan', 'january': 'January', 'feb': 'Feb', 'february': 'February', 'mar': 'Mar', 'march': 'March', 'apr': 'Apr', 'april': 'April', 'may': 'May', 'jun': 'Jun', 'june': 'June', 'jul': 'Jul', 'july': 'July', 'aug': 'Aug', 'august': 'August', 'sep': 'Sep', 'sept': 'Sep', 'september': 'September', 'oct': 'Oct', 'october': 'October', 'nov': 'Nov', 'november': 'November', 'dec': 'Dec', 'december': 'December'}
                    month_name = month_map.get(month_name, month_name)
                    date_str = f'{day}-{month_name}-{year}'
                    df['Date'] = pd.to_datetime(date_str, errors='coerce')
                else:
                    df['Date'] = pd.NaT
                df['Sales Channel'] = 'Noon'
                df['Campaign Type'] = 'Noon Ads'
                df['source_file'] = file
                possible_sku_cols = ['Sku', 'SKU', 'sku', '(Product) Sku']
                sku_col = None
                for c in df.columns:
                    if str(c).strip() in possible_sku_cols:
                        sku_col = c
                        break
                if sku_col:
                    df.rename(columns={sku_col: 'ASIN'}, inplace=True)
                    df['ASIN'] = df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
                all_data.append(df)
            except Exception as e:
                pass
        if all_data:
            merged = pd.concat(all_data, ignore_index=True)
            merged['Date'] = pd.to_datetime(merged['Date'], errors='coerce').dt.normalize()
            if 'ASIN' in merged.columns:
                merged = merged[merged['ASIN'].notna()]
            merged = merged.sort_values(['Date', 'ASIN'])
            merged = merged.drop_duplicates()
            out = os.path.join(output_folder, f'ads_noon_uae_{month}_master.xlsx')
            merged.to_excel(out, index=False)
    noon_ads_parts = []
    for month in MONTHS:
        file_path = os.path.join(NOON_ADS_ROOT, f'{month}_output', f'ads_noon_uae_{month}_master.xlsx')
        if os.path.exists(file_path):
            try:
                df = pd.read_excel(file_path)
                df['source_month'] = month
                noon_ads_parts.append(df)
            except Exception as e:
                pass
    if noon_ads_parts:
        noon_ads_df = pd.concat(noon_ads_parts, ignore_index=True)
    else:
        noon_ads_df = pd.DataFrame()
    if not noon_ads_df.empty:
        noon_ads_df.columns = noon_ads_df.columns.astype(str).str.strip()
        rename_map = {'Sku': 'ASIN', 'SKU': 'ASIN', '(Product) Sku': 'ASIN', 'Views': 'Impressions', 'Orders': 'ads_unit_sold', 'Order': 'ads_unit_sold', 'Spend': 'ads_spend', 'Spends': 'ads_spend', 'Revenue': 'ads_sales', 'Revenue (AED)': 'ads_sales', 'Sales': 'ads_sales', 'CTR': 'Click-Thru Rate (CTR)', 'CPC': 'Cost Per Click (CPC)', 'ROAS': 'Total Return on Advertising Spend (ROAS)', 'ACOS': 'Total Advertising Cost of Sales (ACOS)'}
        noon_ads_df.rename(columns={k: v for k, v in rename_map.items() if k in noon_ads_df.columns}, inplace=True)
        if 'ASIN' in noon_ads_df.columns:
            noon_ads_df['ASIN'] = noon_ads_df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
        if 'Date' in noon_ads_df.columns:
            noon_ads_df['Date'] = pd.to_datetime(noon_ads_df['Date'], errors='coerce').dt.normalize()
        noon_ads_df = noon_ads_df[noon_ads_df['Date'].notna()]
        numeric_cols = ['ads_sales', 'ads_unit_sold', 'ads_spend', 'Impressions', 'Clicks', 'Click-Thru Rate (CTR)', 'Cost Per Click (CPC)', 'Total Advertising Cost of Sales (ACOS)', 'Total Return on Advertising Spend (ROAS)']
        for col in numeric_cols:
            if col in noon_ads_df.columns:
                noon_ads_df[col] = noon_ads_df[col].astype(str).str.replace(',', '', regex=False).str.replace('AED', '', regex=False).str.replace('%', '', regex=False).str.strip().pipe(pd.to_numeric, errors='coerce').fillna(0)
            else:
                noon_ads_df[col] = 0
        noon_ads_df['Sales Channel'] = 'Noon'
        if 'Campaign Type' not in noon_ads_df.columns:
            noon_ads_df['Campaign Type'] = 'Noon Ads'
        dedupe_cols = [c for c in ['ASIN', 'Date', 'Campaign Name', 'Campaign Type'] if c in noon_ads_df.columns]
        if dedupe_cols:
            noon_ads_df = noon_ads_df.drop_duplicates(subset=dedupe_cols, keep='last')
        campaign_cols = ['ASIN', 'Date', 'Sales Channel', 'Campaign Name', 'Campaign Type', 'Portfolio name', 'ads_sales', 'ads_unit_sold', 'ads_spend', 'Impressions', 'Clicks', 'Click-Thru Rate (CTR)', 'Cost Per Click (CPC)', 'Total Advertising Cost of Sales (ACOS)', 'Total Return on Advertising Spend (ROAS)']
        campaign_cols = [c for c in campaign_cols if c in noon_ads_df.columns]
        noon_ads_campaign = noon_ads_df[campaign_cols].copy()
        agg_dict = {'ads_sales': 'sum', 'ads_unit_sold': 'sum', 'ads_spend': 'sum'}
        if 'Impressions' in noon_ads_df.columns:
            agg_dict['Impressions'] = 'sum'
        if 'Clicks' in noon_ads_df.columns:
            agg_dict['Clicks'] = 'sum'
        noon_ads_agg = noon_ads_df.groupby(['ASIN', 'Date'], as_index=False).agg(agg_dict)
        noon_ads_agg['Sales Channel'] = 'Noon'
        helper_df = pd.read_excel(HELPER_FILE, header=1)
        helper_df.columns = helper_df.columns.astype(str).str.strip()
        noon_helper_col = None
        for col in helper_df.columns:
            clean_col = str(col).replace('\n', ' ').strip().lower()
            if 'noon core' in clean_col:
                noon_helper_col = col
                break
        helper_df.rename(columns={noon_helper_col: 'ASIN'}, inplace=True)
        helper_df['ASIN'] = helper_df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
        helper_df.rename(columns={'Product Description(Cleaned)': 'Product Name', 'Category': 'Product Category', 'Product Type': 'Product Sub Category', 'Size': 'Pack Size'}, inplace=True)
        helper_cols = ['ASIN', 'Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size', 'VC Ideal Price']
        helper_cols = [c for c in helper_cols if c in helper_df.columns]
        helper_df = helper_df[helper_cols]
        helper_df = helper_df[helper_df['ASIN'].notna()]
        helper_df = helper_df[helper_df['ASIN'] != '']
        helper_df = helper_df.drop_duplicates(subset=['ASIN'])
        noon_ads_campaign = noon_ads_campaign.merge(helper_df, on='ASIN', how='left')
        metadata_cols = ['Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size']
        for col in metadata_cols:
            if col in noon_ads_campaign.columns:
                noon_ads_campaign[col] = noon_ads_campaign[col].fillna('Unknown')
        drop_cols = [c for c in noon_ads_campaign.columns if c.endswith('_x') or c.endswith('_y')]
        if drop_cols:
            noon_ads_campaign.drop(columns=drop_cols, inplace=True)
    else:
        noon_ads_campaign = pd.DataFrame()
        noon_ads_agg = pd.DataFrame()
    if not noon_ads_campaign.empty:
        if 'Brand' in noon_ads_campaign.columns:
            pass
    noon_rev_parts = []
    noon_rev_parts = []
    for month in MONTHS:
        month_folder = os.path.join(NOON_REV_ROOT, month)
        if not os.path.isdir(month_folder):
            continue
        for file in sorted(os.listdir(month_folder)):
            if file.startswith('~$'):
                continue
            if not file.lower().endswith(('.csv', '.xlsx', '.xls')):
                continue
            file_path = os.path.join(month_folder, file)
            try:
                if file.lower().endswith('.csv'):
                    df = pd.read_csv(file_path)
                else:
                    df = pd.read_excel(file_path)
                df.columns = df.columns.astype(str).str.strip()
                normalized_columns = {}
                for col in df.columns:
                    clean_col = str(col).strip().lower().replace('_', ' ')
                    if clean_col == 'zsku':
                        normalized_columns[col] = 'ZSKU'
                    elif clean_col == 'nsku':
                        normalized_columns[col] = 'nsku'
                    elif clean_col in {'qty', 'quantity'}:
                        normalized_columns[col] = 'Qty'
                    elif clean_col in {'revenue', 'sales', 'revenue (aed)'}:
                        normalized_columns[col] = 'Revenue'
                    elif clean_col == 'date':
                        normalized_columns[col] = 'Date'
                df.rename(columns=normalized_columns, inplace=True)
                df['source_file'] = file
                df['source_month'] = month
                if 'ZSKU' not in df.columns:
                    pass
                else:
                    zsku_count = df['ZSKU'].notna().sum()
                noon_rev_parts.append(df)
            except Exception as e:
                pass
    if noon_rev_parts:
        noon_rev_df = pd.concat(noon_rev_parts, ignore_index=True)
    else:
        noon_rev_df = pd.DataFrame()
    if not noon_rev_df.empty:
        noon_rev_df.columns = noon_rev_df.columns.astype(str).str.strip()
        for _drop_col in ['nsku', 'NSKU', 'Nsku']:
            if _drop_col in noon_rev_df.columns:
                noon_rev_df.drop(columns=[_drop_col], inplace=True)
        rename_map = {'ZSKU': 'ASIN', 'Sku': 'ASIN', 'SKU': 'ASIN', 'Qty': 'total_units', 'Quantity': 'total_units', 'Revenue': 'total_sales', 'Sales': 'total_sales', 'Revenue (AED)': 'total_sales'}
        noon_rev_df.rename(columns={k: v for k, v in rename_map.items() if k in noon_rev_df.columns}, inplace=True)
        duplicate_columns = noon_rev_df.columns[noon_rev_df.columns.duplicated()].tolist()
        if duplicate_columns:
            noon_rev_df = noon_rev_df.loc[:, ~noon_rev_df.columns.duplicated()]
        required_cols = ['ASIN', 'Date', 'total_sales', 'total_units']
        missing_cols = [c for c in required_cols if c not in noon_rev_df.columns]
        if missing_cols:
            pass
        noon_rev_df['ASIN'] = noon_rev_df['ASIN'].astype('string').str.upper().str.strip().str.replace('.0', '', regex=False).replace({'NAN': pd.NA, 'NONE': pd.NA, 'NULL': pd.NA, '': pd.NA})
        if 'source_month' in noon_rev_df.columns:
            asin_check = noon_rev_df.groupby('source_month', dropna=False).agg(rows=('ASIN', 'size'), asin_present=('ASIN', lambda x: x.notna().sum()), asin_missing=('ASIN', lambda x: x.isna().sum())).reset_index()
        before_asin_filter = len(noon_rev_df)
        noon_rev_df = noon_rev_df[noon_rev_df['ASIN'].notna()].copy()
        removed_asin_rows = before_asin_filter - len(noon_rev_df)
        if removed_asin_rows:
            pass

        def parse_mixed_dates(x):
            """
            Parse date strings safely for UAE data (DD-first convention).
            %m/%d/%Y removed to prevent 01/06/2026 → Jan-6 misparse.
            Dates outside 2020-2030 are rejected as invalid year artifacts.
            """
            if pd.isna(x):
                return pd.NaT
            x = str(x).strip()
            formats = ['%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d', '%d.%m.%Y', '%d %b %Y', '%b %d %Y']
            for fmt in formats:
                try:
                    result = pd.to_datetime(x, format=fmt)
                    if 2020 <= result.year <= 2030:
                        return result
                except Exception:
                    continue
            try:
                result = pd.to_datetime(x, dayfirst=True, errors='coerce')
                if pd.notna(result) and 2020 <= result.year <= 2030:
                    return result
            except Exception:
                pass
            return pd.NaT
        noon_rev_df['Date'] = noon_rev_df['Date'].apply(parse_mixed_dates).dt.normalize()
        noon_rev_df = noon_rev_df[noon_rev_df['Date'].notna()]
        noon_rev_df['total_sales'] = noon_rev_df['total_sales'].astype(str).str.replace(',', '', regex=False).str.replace('AED', '', regex=False).str.replace('aed', '', regex=False).str.strip().pipe(pd.to_numeric, errors='coerce').fillna(0)
        noon_rev_df['total_units'] = pd.to_numeric(noon_rev_df['total_units'], errors='coerce').fillna(0).astype(int)
        noon_rev_df = noon_rev_df.groupby(['ASIN', 'Date'], as_index=False).agg({'total_sales': 'sum', 'total_units': 'sum'})
        noon_rev_df['Sales Channel'] = 'Noon'
        noon_rev_df = noon_rev_df.sort_values(['ASIN', 'Date'])
        helper_df = pd.read_excel(HELPER_FILE, header=1)
        helper_df.columns = helper_df.columns.astype(str).str.strip()
        helper_key = None
        for col in helper_df.columns:
            clean_col = str(col).replace('\n', ' ').strip().lower()
            if 'noon core' in clean_col:
                helper_key = col
                break
        helper_df.rename(columns={helper_key: 'ASIN'}, inplace=True)
        helper_df['ASIN'] = helper_df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
        helper_df.rename(columns={'Product Description(Cleaned)': 'Product Name', 'Category': 'Product Category', 'Product Type': 'Product Sub Category', 'Size': 'Pack Size'}, inplace=True)
        helper_cols = ['ASIN', 'Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size', 'VC Ideal Price']
        helper_cols = [c for c in helper_cols if c in helper_df.columns]
        helper_df = helper_df[helper_cols]
        helper_df = helper_df.drop_duplicates(subset=['ASIN'])
        noon_rev_df = noon_rev_df.merge(helper_df, on='ASIN', how='left')
        metadata_cols = ['Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size']
        for col in metadata_cols:
            if col in noon_rev_df.columns:
                noon_rev_df[col] = noon_rev_df[col].fillna('Unknown')
    if not noon_rev_df.empty:
        pass
    if not noon_rev_df.empty:
        august_df = noon_rev_df[noon_rev_df['Date'].dt.year.eq(2026) & noon_rev_df['Date'].dt.month.eq(8)].copy()
        if august_df.empty:
            pass
    nms_rev_parts = []
    nms_rev_parts = []
    for month in MONTHS:
        month_folder = os.path.join(NMS_REV_ROOT, month)
        if not os.path.isdir(month_folder):
            continue
        for file in sorted(os.listdir(month_folder)):
            if file.startswith('~$'):
                continue
            if not file.lower().endswith(('.csv', '.xlsx', '.xls')):
                continue
            file_path = os.path.join(month_folder, file)
            try:
                if file.lower().endswith('.csv'):
                    df = pd.read_csv(file_path)
                else:
                    df = pd.read_excel(file_path)
                df.columns = df.columns.astype(str).str.strip()
                normalized_columns = {}
                for col in df.columns:
                    clean_col = str(col).strip().lower().replace('_', ' ')
                    if clean_col == 'zsku':
                        normalized_columns[col] = 'ZSKU'
                    elif clean_col == 'nsku':
                        normalized_columns[col] = 'nsku'
                    elif clean_col in {'qty', 'quantity'}:
                        normalized_columns[col] = 'Qty'
                    elif clean_col in {'revenue', 'sales', 'revenue (aed)'}:
                        normalized_columns[col] = 'Revenue'
                    elif clean_col == 'date':
                        normalized_columns[col] = 'Date'
                df.rename(columns=normalized_columns, inplace=True)
                df['source_file'] = file
                df['source_month'] = month
                if 'ZSKU' not in df.columns:
                    pass
                else:
                    zsku_count = df['ZSKU'].notna().sum()
                nms_rev_parts.append(df)
            except Exception as e:
                pass
    if nms_rev_parts:
        nms_rev_df = pd.concat(nms_rev_parts, ignore_index=True)
    else:
        nms_rev_df = pd.DataFrame()
    if not nms_rev_df.empty:
        nms_rev_df.columns = nms_rev_df.columns.astype(str).str.strip()
        if 'ZSKU' not in nms_rev_df.columns:
            raise ValueError('❌ ZSKU column not found in Noon Minutes Revenue files')
        for _drop_col in ['nsku', 'NSKU', 'Nsku']:
            if _drop_col in nms_rev_df.columns:
                nms_rev_df.drop(columns=[_drop_col], inplace=True)
        rename_map = {'ZSKU': 'ASIN', 'Sku': 'ASIN', 'SKU': 'ASIN', 'Qty': 'total_units', 'Quantity': 'total_units', 'Revenue': 'total_sales', 'Sales': 'total_sales', 'Revenue (AED)': 'total_sales'}
        nms_rev_df.rename(columns={k: v for k, v in rename_map.items() if k in nms_rev_df.columns}, inplace=True)
        required_cols = ['ASIN', 'Date', 'total_sales', 'total_units']
        missing_cols = [c for c in required_cols if c not in nms_rev_df.columns]
        if missing_cols:
            raise ValueError(f'❌ Required Noon Minutes Revenue columns are missing: {missing_cols}')
        duplicate_columns = nms_rev_df.columns[nms_rev_df.columns.duplicated()].tolist()
        if duplicate_columns:
            nms_rev_df = nms_rev_df.loc[:, ~nms_rev_df.columns.duplicated()]
        keep_cols = ['ASIN', 'Date', 'total_sales', 'total_units', 'source_month', 'source_file']
        available_cols = [c for c in keep_cols if c in nms_rev_df.columns]
        nms_rev_df = nms_rev_df[available_cols].copy()
        nms_rev_df['ASIN'] = nms_rev_df['ASIN'].astype('string').str.upper().str.strip().str.replace('.0', '', regex=False).replace({'NAN': pd.NA, 'NONE': pd.NA, 'NULL': pd.NA, '': pd.NA})
        if 'source_month' in nms_rev_df.columns:
            asin_check = nms_rev_df.groupby('source_month', dropna=False).agg(rows=('ASIN', 'size'), asin_present=('ASIN', lambda x: x.notna().sum()), asin_missing=('ASIN', lambda x: x.isna().sum())).reset_index()
        before_asin_filter = len(nms_rev_df)
        nms_rev_df = nms_rev_df[nms_rev_df['ASIN'].notna()].copy()
        removed_asin_rows = before_asin_filter - len(nms_rev_df)
        if removed_asin_rows:
            pass

        def parse_mixed_dates(x):
            """
            Parse date strings safely for UAE data (DD-first convention).
            %m/%d/%Y removed to prevent 01/06/2026 → Jan-6 misparse.
            Dates outside 2020-2030 are rejected as invalid year artifacts.
            """
            if pd.isna(x):
                return pd.NaT
            x = str(x).strip()
            formats = ['%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d', '%d.%m.%Y', '%d %b %Y', '%b %d %Y']
            for fmt in formats:
                try:
                    result = pd.to_datetime(x, format=fmt)
                    if 2020 <= result.year <= 2030:
                        return result
                except Exception:
                    continue
            try:
                result = pd.to_datetime(x, dayfirst=True, errors='coerce')
                if pd.notna(result) and 2020 <= result.year <= 2030:
                    return result
            except Exception:
                pass
            return pd.NaT
        nms_rev_df['Date'] = nms_rev_df['Date'].apply(parse_mixed_dates).dt.normalize()
        nms_rev_df = nms_rev_df[nms_rev_df['Date'].notna()]
        nms_rev_df['total_sales'] = nms_rev_df['total_sales'].astype(str).str.replace(',', '', regex=False).str.replace('AED', '', regex=False).str.replace('aed', '', regex=False).str.strip().pipe(pd.to_numeric, errors='coerce').fillna(0)
        nms_rev_df['total_units'] = pd.to_numeric(nms_rev_df['total_units'], errors='coerce').fillna(0).astype(int)
        nms_rev_df = nms_rev_df.groupby(['ASIN', 'Date'], as_index=False).agg({'total_sales': 'sum', 'total_units': 'sum'})
        nms_rev_df['Sales Channel'] = 'Noon Minutes'
        nms_rev_df = nms_rev_df.sort_values(['ASIN', 'Date'])
        helper_df = pd.read_excel(HELPER_FILE, header=1)
        helper_df.columns = helper_df.columns.astype(str).str.strip()
        helper_key = None
        for col in helper_df.columns:
            clean_col = str(col).replace('\n', ' ').replace('_', ' ').strip().lower()
            if 'product code' in clean_col and 'noon minutes' in clean_col:
                helper_key = col
                break
        if helper_key is None:
            raise ValueError('❌ Could not find the Noon Minutes Product Code column in the helper file.')
        helper_df.rename(columns={helper_key: 'ASIN'}, inplace=True)
        helper_df['ASIN'] = helper_df['ASIN'].astype('string').str.upper().str.strip().str.replace('.0', '', regex=False).replace({'NAN': pd.NA, 'NONE': pd.NA, 'NULL': pd.NA, '': pd.NA})
        helper_df.rename(columns={'Product Description(Cleaned)': 'Product Name', 'Category': 'Product Category', 'Product Type': 'Product Sub Category', 'Size': 'Pack Size'}, inplace=True)
        helper_cols = ['ASIN', 'Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size', 'VC Ideal Price']
        helper_cols = [c for c in helper_cols if c in helper_df.columns]
        helper_df = helper_df[helper_cols]
        helper_df = helper_df.drop_duplicates(subset=['ASIN'])
        nms_rev_df = nms_rev_df.merge(helper_df, on='ASIN', how='left')
        metadata_cols = ['Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size']
        for col in metadata_cols:
            if col in nms_rev_df.columns:
                nms_rev_df[col] = nms_rev_df[col].fillna('Unknown')
    if not nms_rev_df.empty:
        pass
    if not nms_rev_df.empty:
        august_df = nms_rev_df[nms_rev_df['Date'].dt.year.eq(2026) & nms_rev_df['Date'].dt.month.eq(8)].copy()
        if august_df.empty:
            pass
        else:
            sample_cols = ['ASIN', 'Date', 'total_sales', 'total_units', 'Sales Channel', 'Brand', 'Product Name']
            sample_cols = [c for c in sample_cols if c in august_df.columns]
    nms_ads_parts = []
    for month in MONTHS:
        file_path = os.path.join(NMS_ADS_ROOT, month, f'noon_minuts_ads_{month}_{YEAR}.csv')
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path)
                if 'Date' in df.columns:
                    pass
                df['processed_month'] = month
                nms_ads_parts.append(df)
            except Exception as e:
                pass
    if nms_ads_parts:
        nms_ads_df = pd.concat(nms_ads_parts, ignore_index=True)
    else:
        nms_ads_df = pd.DataFrame()
    if not nms_ads_df.empty:
        nms_ads_df.columns = nms_ads_df.columns.astype(str).str.strip()
        rename_map = {'SKU': 'ASIN', 'Sku': 'ASIN', 'sku': 'ASIN', 'Views': 'Impressions', 'Spends': 'ads_spend', 'Spend': 'ads_spend', 'Revenue': 'ads_sales', 'Revenue (AED)': 'ads_sales', 'Orders': 'ads_unit_sold', 'Portfolio Name': 'Portfolio name'}
        nms_ads_df.rename(columns={k: v for k, v in rename_map.items() if k in nms_ads_df.columns}, inplace=True)
        nms_ads_df = nms_ads_df.loc[:, ~nms_ads_df.columns.duplicated()]
        nms_ads_df['ASIN'] = nms_ads_df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)

        def parse_date(x):
            if pd.isna(x):
                return pd.NaT
            x = str(x).strip()
            formats = ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d', '%d-%b-%Y', '%d-%B-%Y', '%d %b %Y', '%d %B %Y', '%m/%d/%Y', '%m-%d-%Y']
            for fmt in formats:
                try:
                    return pd.to_datetime(x, format=fmt)
                except:
                    pass
            return pd.to_datetime(x, errors='coerce', dayfirst=True)
        nms_ads_df['Date'] = nms_ads_df['Date'].apply(parse_date).dt.normalize()
        nms_ads_df = nms_ads_df[nms_ads_df['Date'].notna()]
        nms_ads_df['Sales Channel'] = 'Noon Minutes'
        if 'Campaign Type' not in nms_ads_df.columns:
            nms_ads_df['Campaign Type'] = 'Noon Minutes Ads'
        if 'Portfolio name' not in nms_ads_df.columns:
            nms_ads_df['Portfolio name'] = ''
        numeric_cols = ['ads_sales', 'ads_unit_sold', 'ads_spend', 'Impressions', 'Clicks']
        for col in numeric_cols:
            if col in nms_ads_df.columns:
                nms_ads_df[col] = nms_ads_df[col].astype(str).str.replace(',', '', regex=False).str.replace('%', '', regex=False).str.replace('AED', '', regex=False).str.strip().pipe(pd.to_numeric, errors='coerce').fillna(0)
            else:
                nms_ads_df[col] = 0
            if 'CTR' in nms_ads_df.columns:
                nms_ads_df['Click-Thru Rate (CTR)'] = pd.to_numeric(nms_ads_df['CTR'], errors='coerce').fillna(0)
            else:
                nms_ads_df['Click-Thru Rate (CTR)'] = 0
            if 'CPC' in nms_ads_df.columns:
                nms_ads_df['Cost Per Click (CPC)'] = pd.to_numeric(nms_ads_df['CPC'], errors='coerce').fillna(0)
            else:
                nms_ads_df['Cost Per Click (CPC)'] = 0
            if 'ROAS' in nms_ads_df.columns:
                nms_ads_df['Total Return on Advertising Spend (ROAS)'] = pd.to_numeric(nms_ads_df['ROAS'], errors='coerce').fillna(0)
            else:
                nms_ads_df['Total Return on Advertising Spend (ROAS)'] = 0
            nms_ads_df['Total Advertising Cost of Sales (ACOS)'] = np.where(nms_ads_df['ads_sales'] > 0, (nms_ads_df['ads_spend'] / nms_ads_df['ads_sales'] * 100).round(2), 0)
            nms_ads_df['CVR'] = np.where(nms_ads_df['Clicks'] > 0, (nms_ads_df['ads_unit_sold'] / nms_ads_df['Clicks'] * 100).round(2), 0)
        helper_df = pd.read_excel(HELPER_FILE, header=1)
        helper_df.columns = helper_df.columns.astype(str).str.strip()
        helper_key = None
        for col in helper_df.columns:
            clean_col = str(col).replace('\n', ' ').replace('_', ' ').strip().lower()
            if 'product code' in clean_col and 'noon minutes' in clean_col:
                helper_key = col
                break
        helper_df.rename(columns={helper_key: 'ASIN'}, inplace=True)
        helper_df['ASIN'] = helper_df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
        helper_df.rename(columns={'Product Description(Cleaned)': 'Product Name', 'Category': 'Product Category', 'Product Type': 'Product Sub Category', 'Size': 'Pack Size'}, inplace=True)
        helper_cols = ['ASIN', 'Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size', 'VC Ideal Price']
        helper_cols = [c for c in helper_cols if c in helper_df.columns]
        helper_df = helper_df[helper_cols]
        helper_df = helper_df.drop_duplicates(subset=['ASIN'])
        nms_ads_df = nms_ads_df.merge(helper_df, on='ASIN', how='left')
        metadata_cols = ['Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size']
        for col in metadata_cols:
            if col in nms_ads_df.columns:
                nms_ads_df[col] = nms_ads_df[col].fillna('Unknown')
        _camp_cols = ['ASIN', 'Date', 'Sales Channel', 'Campaign Name', 'Campaign Type', 'Portfolio name', 'ads_sales', 'ads_unit_sold', 'ads_spend', 'Impressions', 'Clicks', 'Click-Thru Rate (CTR)', 'Cost Per Click (CPC)', 'Total Advertising Cost of Sales (ACOS)', 'Total Return on Advertising Spend (ROAS)', 'CVR', 'Brand', 'Product Name', 'Product Category', 'Product Sub Category', 'Pack Type', 'Pack Size', 'VC Ideal Price']
        _camp_cols = [c for c in _camp_cols if c in nms_ads_df.columns]
        nms_ads_campaign = nms_ads_df[_camp_cols].copy()
        nms_ads_agg = nms_ads_df.groupby(['ASIN', 'Date', 'Sales Channel'], as_index=False).agg({'ads_sales': 'sum', 'ads_unit_sold': 'sum', 'ads_spend': 'sum'})
    else:
        nms_ads_campaign = pd.DataFrame()
        nms_ads_agg = pd.DataFrame()
    if not nms_ads_campaign.empty:
        pass
    xls = pd.ExcelFile(HELPER_FILE)
    helper_raw = pd.read_excel(HELPER_FILE, sheet_name='Master Sheet', header=1)
    helper_raw.columns = helper_raw.columns.astype(str).str.strip()

    def _match_col(cols, *keywords):
        """Return first column whose normalised name contains ALL keywords."""
        for c in cols:
            norm = str(c).replace('\n', ' ').replace('_', ' ').strip().lower()
            if all((k in norm for k in keywords)):
                return c
        return None
    _asin_col = _match_col(helper_raw.columns, 'amazon', 'asin')
    _nc_col = _match_col(helper_raw.columns, 'product code', 'noon core') or _match_col(helper_raw.columns, 'noon core')
    _nms_col = _match_col(helper_raw.columns, 'product code', 'noon minutes') or _match_col(helper_raw.columns, 'noon minutes')
    _name_col = _match_col(helper_raw.columns, 'product description')
    _cat_col = _match_col(helper_raw.columns, 'category')
    _sub_col = _match_col(helper_raw.columns, 'product type')
    _size_col = _match_col(helper_raw.columns, 'size')
    _pt_col = _match_col(helper_raw.columns, 'pack type')
    _vc_col = _match_col(helper_raw.columns, 'vc ideal price')
    rename_map = {}
    if _asin_col:
        rename_map[_asin_col] = 'ASIN'
    if _nc_col:
        rename_map[_nc_col] = 'NC_NIN'
    if _nms_col:
        rename_map[_nms_col] = 'NMs_NIN'
    if _name_col:
        rename_map[_name_col] = 'Product Name'
    if _cat_col:
        rename_map[_cat_col] = 'Product Category'
    if _sub_col:
        rename_map[_sub_col] = 'Product Sub Category'
    if _size_col:
        rename_map[_size_col] = 'Pack Size'
    if _pt_col:
        rename_map[_pt_col] = 'Pack Type'
    if _vc_col:
        rename_map[_vc_col] = 'VC Ideal Price'
    helper_raw.rename(columns=rename_map, inplace=True)
    if 'SC Ideal Price' not in helper_raw.columns:
        helper_raw['SC Ideal Price'] = 0

    def _clean_asin_key(series):
        """Clean Amazon ASINs — strips trailing digit suffix like -1 (not part of Amazon ASIN)."""
        return series.astype(str).str.upper().str.strip().str.replace('\xa0', '', regex=False).str.replace('.0', '', regex=False).str.replace('\\s+', '', regex=True).str.replace('-\\d+$', '', regex=True).replace({'NAN': np.nan, '': np.nan, 'NONE': np.nan, '-': np.nan})

    def _clean_nin_key(series):
        """Clean Noon NINs — KEEP digit suffix like -1 (it IS part of the Noon NIN, e.g. Z...Z-1)."""
        return series.astype(str).str.upper().str.strip().str.replace('\xa0', '', regex=False).str.replace('.0', '', regex=False).str.replace('\\s+', '', regex=True).replace({'NAN': np.nan, '': np.nan, 'NONE': np.nan, '-': np.nan})

    def _clean_key(series):
        return _clean_nin_key(series)
    if 'ASIN' in helper_raw.columns:
        helper_raw['ASIN'] = _clean_asin_key(helper_raw['ASIN'])
    if 'NC_NIN' in helper_raw.columns:
        helper_raw['NC_NIN'] = _clean_nin_key(helper_raw['NC_NIN'])
    if 'NMs_NIN' in helper_raw.columns:
        helper_raw['NMs_NIN'] = _clean_nin_key(helper_raw['NMs_NIN'])
    if 'Brand' in helper_raw.columns:
        helper_raw['Brand'] = helper_raw['Brand'].astype(str).str.strip().replace({'': np.nan, 'nan': np.nan, 'None': np.nan}).fillna('Emami')
    if 'Pack Size' in helper_raw.columns:
        helper_raw['Pack Size'] = pd.to_numeric(helper_raw['Pack Size'].astype(str).str.extract('(\\d+)')[0], errors='coerce').fillna(0)
    if 'VC Ideal Price' in helper_raw.columns:
        helper_raw['VC Ideal Price'] = pd.to_numeric(helper_raw['VC Ideal Price'].astype(str).str.replace(',', '', regex=False).str.strip(), errors='coerce').fillna(0)
    INFO_COLS = [c for c in ['Brand', 'Product Category', 'Product Sub Category', 'Product Name', 'Pack Type', 'Pack Size', 'VC Ideal Price', 'SC Ideal Price'] if c in helper_raw.columns]
    h_asin = helper_raw[helper_raw['ASIN'].notna()].sort_values('Brand', na_position='last').drop_duplicates(subset=['ASIN'], keep='first')[['ASIN'] + INFO_COLS].copy()
    h_nc = helper_raw[helper_raw['NC_NIN'].notna()].sort_values('Brand', na_position='last').drop_duplicates(subset=['NC_NIN'], keep='first')[['NC_NIN'] + INFO_COLS].copy()
    h_nms = helper_raw[helper_raw['NMs_NIN'].notna()].sort_values('Brand', na_position='last').drop_duplicates(subset=['NMs_NIN'], keep='first')[['NMs_NIN'] + INFO_COLS].copy()
    _MONTH_NUM = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}

    def _read_file(fp):
        if fp.lower().endswith('.csv'):
            return pd.read_csv(fp)
        return pd.read_excel(fp)

    def _clean_num(series):
        return pd.to_numeric(series.astype(str).str.replace('AED', '', regex=False).str.replace(',', '', regex=False).str.replace('\xa0', '', regex=False).str.strip(), errors='coerce').fillna(0)

    def _clean_key(obj):
        """
        Clean Noon NINs.
        Handles both Series and DataFrame.
        """
        if isinstance(obj, pd.DataFrame):
            obj = obj.iloc[:, 0]
        return obj.astype(str).str.upper().str.strip().str.replace('\xa0', '', regex=False).str.replace('.0', '', regex=False).str.replace('\\s+', '', regex=True).replace({'NAN': np.nan, '': np.nan, 'NONE': np.nan, '-': np.nan})

    def load_monthly_merged_files(root, months, prefix, label):
        dfs = []
        for month in months:
            fp = os.path.join(root, month, f'{prefix}_{month}_{YEAR}.xlsx')
            if not os.path.exists(fp):
                continue
            try:
                df = pd.read_excel(fp, dtype=str)
                df.columns = df.columns.astype(str).str.strip()
                dfs.append(df)
            except Exception as e:
                pass
        if dfs:
            final_df = pd.concat(dfs, ignore_index=True)
            return final_df
        return pd.DataFrame()

    def _resolve_noon_date(df, label=''):
        """
        Deterministically compute ONE clean 'Date' Series for noon/NMs inventory rows,
        independent of glob() order, concat column order, or which files were present.

        Priority per row (NOT per column — every row picks its own best source):
          1. A genuine "Date"-named column (already-parsed dates, e.g. from a
             pre-saved merged_*.xlsx file built by the consolidation step).
          2. "Refresh Time" / "Snapshot Date" / "Report Date" text columns
             (e.g. "17 Jun 2026, 11:05:00" from raw daily exports).
          3. Derived from the day-folder name (_day / _month columns), for files
             that carry no date information of their own.

        Any resulting date outside 2020–2035 is treated as invalid (NaT) — this
        catches stray old files / bad parses instead of silently mixing them in.
        """
        cols_lower = {c.strip().lower(): c for c in df.columns}
        date_priority = ['date', 'snapshot date', 'report date', 'snapshot_date', 'refresh time']
        candidates = [cols_lower[name] for name in date_priority if name in cols_lower]
        if candidates:
            raw_value = pd.Series(pd.NA, index=df.index, dtype=object)
            for col_name in candidates:
                col = df[col_name]
                if isinstance(col, pd.DataFrame):
                    col = col.iloc[:, 0]
                still_missing = raw_value.isna()
                raw_value.loc[still_missing] = col.loc[still_missing]

            def _parse_one(v):
                if pd.isna(v):
                    return pd.NaT
                if isinstance(v, (pd.Timestamp, np.datetime64)):
                    return pd.Timestamp(v).normalize()
                s = str(v).replace('\u202f', ' ').replace('\xa0', ' ').strip()
                if not s:
                    return pd.NaT
                return pd.to_datetime(s, errors='coerce', format='mixed')
            parsed = raw_value.map(_parse_one)
        else:
            parsed = pd.Series(pd.NaT, index=df.index)
        missing = parsed.isna()
        if missing.any() and '_day' in df.columns and ('_month' in df.columns):

            def _from_day_folder(r):
                s = str(r['_day']).strip()
                month_num = _MONTH_NUM.get(str(r['_month']).strip().lower(), 1)
                try:
                    ts = pd.to_datetime(s, dayfirst=True, errors='coerce')
                    if pd.notna(ts) and 2020 <= ts.year <= 2035:
                        return ts.normalize()
                except Exception:
                    pass
                m = re.search('(\\d+)', s)
                day = int(m.group(1)) if m else 1
                if day < 1 or day > 31:
                    day = 1
                try:
                    return pd.Timestamp(year=YEAR, month=month_num, day=day)
                except Exception:
                    return pd.NaT
            parsed.loc[missing] = df.loc[missing].apply(_from_day_folder, axis=1)
        parsed = pd.to_datetime(parsed, errors='coerce').dt.normalize()
        valid = parsed.dt.year.between(2020, 2035)
        bad_n = int((~valid & parsed.notna()).sum())
        if bad_n > 0:
            bad_years = sorted(parsed[~valid & parsed.notna()].dt.year.unique().tolist())
        parsed = parsed.where(valid, other=pd.NaT)
        return parsed

    def standardise_noon_inv(raw, stock_col, label):
        if raw.empty:
            return pd.DataFrame()
        df = raw.copy()
        col_map = {}
        stock_mapped = False
        for c in df.columns:
            cl = c.strip().lower()
            if cl in ['zsku', 'sku', 'nin', 'nins', 'product code', 'product_code']:
                col_map[c] = 'NINs'
            elif cl in ['barcode', 'ean']:
                col_map[c] = 'Barcode'
            elif cl == stock_col.lower() and (not stock_mapped):
                col_map[c] = 'Available Inventory'
                stock_mapped = True
        df.rename(columns=col_map, inplace=True)
        df = df.loc[:, ~df.columns.duplicated()]
        if 'NINs' not in df.columns:
            raise KeyError(f'[{label}] NIN column not found')
        df['NINs'] = _clean_key(df['NINs'])
        if 'Barcode' not in df.columns:
            df['Barcode'] = ''
        df['Barcode'] = df['Barcode'].astype(str).str.strip()
        df['Available Inventory'] = _clean_num(df['Available Inventory'])
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.normalize()
        df = df[df['Date'].notna()]
        df = df[df['NINs'].notna()]
        agg = df.groupby(['NINs', 'Date'], as_index=False, dropna=False).agg({'Available Inventory': 'sum', 'Barcode': 'first'})
        return agg

    def compute_l30_dos(inv_df, rev_df, id_col, inventory_is_current=False):
        """
        30-calendar-day Last 30 Days Sales + DOS, with channel-aware date anchoring.

        T-2 RULE — applies to ALL channels (Noon, Noon Minutes, Amazon):
            pass
        ════════════════════════════════════════════════════════════════════
        For EVERY inventory snapshot date D, the 30-day window is:
            t_end   = D - 2 days          (T-2: latest confirmed sales)
            t_start = t_end - 29 days     (30 days inclusive)

        Verified correct against noon_dos_calculator.py:
            Inventory 19-Jun → T-2=17-Jun → window 19-May to 17-Jun = 609 units ✅

        NOTE on ASIN IDs for Noon/NMs:
            Sales CSVs have BOTH 'nsku' (col 7) and 'ZSKU' (col 8).
            ALWAYS use ZSKU — it is the correct Noon product identifier.
            nsku (e.g. N28940734A) is an internal warehouse SKU, NOT a NIN.
            Cells 32/34 drop nsku before rename so only ZSKU → ASIN.

        inv_df : [id_col, Date, Available Inventory]
        rev_df : [id_col, Date, total_units]  ← must use ZSKU as id_col for Noon/NMs
        inventory_is_current : True  → Noon/NMs (inv snapshot = T-0 current stock)
                               False → Amazon   (inv snapshot already at T-2)
        Both use the same T-2 formula — inventory_is_current kept for clarity.
        """
        df = inv_df.copy()
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df[df['Date'].notna()].copy()
        if rev_df is not None and (not rev_df.empty):
            rev = rev_df.copy()
            if 'total_units' not in rev.columns:
                rev['total_units'] = 0
            rev['total_units'] = _clean_num(rev['total_units'])
            rev['Date'] = pd.to_datetime(rev['Date'], errors='coerce').dt.normalize()
            rev = rev[rev['Date'].notna()]
            daily_rev = rev.groupby([id_col, 'Date'], as_index=False)['total_units'].sum()
        else:
            daily_rev = pd.DataFrame(columns=[id_col, 'Date', 'total_units'])
        df = df.sort_values([id_col, 'Date'])
        merged_parts = []
        for asin, inv_grp in df.groupby(id_col):
            inv_grp = inv_grp.copy()
            sales_grp = daily_rev[daily_rev[id_col] == asin][['Date', 'total_units']].copy()
            if sales_grp.empty:
                inv_grp['Last 30 Days Sales'] = 0.0
            else:
                sales_grp['Date'] = pd.to_datetime(sales_grp['Date'], errors='coerce').dt.normalize()
                sales_grp = sales_grp.set_index('Date').sort_index()['total_units']
                last_sales_date = sales_grp.index.max()
                l30_list = []
                for inv_date in inv_grp['Date']:
                    if inventory_is_current:
                        t_end = inv_date - pd.Timedelta(days=2)
                        t_start = t_end - pd.Timedelta(days=29)
                    else:
                        t_end = inv_date - pd.Timedelta(days=2)
                        t_start = t_end - pd.Timedelta(days=29)
                    if t_end > last_sales_date:
                        t_end = last_sales_date
                        t_start = t_end - pd.Timedelta(days=29)
                    mask = (sales_grp.index >= t_start) & (sales_grp.index <= t_end)
                    l30_list.append(float(sales_grp.loc[mask].sum()))
                inv_grp['Last 30 Days Sales'] = l30_list
            merged_parts.append(inv_grp)
        df = pd.concat(merged_parts, ignore_index=True) if merged_parts else df
        df['Daily Sales Rate'] = np.where(df['Last 30 Days Sales'] > 0, df['Last 30 Days Sales'] / 30, 0)
        dos_raw = np.where(df['Daily Sales Rate'] > 0, df['Available Inventory'] / df['Daily Sales Rate'], np.nan)
        df['DOS'] = pd.Series(dos_raw, dtype=float).replace([np.inf, -np.inf], np.nan).fillna(0).round(0).clip(upper=3650).astype('Int64')
        df.drop(columns=['Daily Sales Rate'], inplace=True, errors='ignore')
        return df

    def _apply_helper_map(inv_df, h_df, h_key, id_col, info_cols):
        """Map helper metadata onto inv_df[id_col] → h_df[h_key]."""
        inv_df = inv_df.copy()
        inv_df.drop(columns=[c for c in info_cols if c in inv_df.columns], inplace=True, errors='ignore')
        h = h_df[[h_key] + [c for c in info_cols if c in h_df.columns]].dropna(subset=[h_key]).drop_duplicates(subset=[h_key]).rename(columns={h_key: id_col})
        inv_df = inv_df.merge(h, on=id_col, how='left')
        for col in list(inv_df.columns):
            if col.endswith('_x'):
                base = col[:-2]
                y = base + '_y'
                inv_df[base] = inv_df[col].combine_first(inv_df.get(y, pd.Series(dtype=object)))
                inv_df.drop(columns=[col, y], inplace=True, errors='ignore')
        for col in info_cols:
            if col not in inv_df.columns:
                inv_df[col] = np.nan
            inv_df[col] = inv_df[col].replace({'': np.nan, 'nan': np.nan, 'None': np.nan}).fillna('Unknown')
        return inv_df
    INFO_COLS = [c for c in ['Brand', 'Product Category', 'Product Sub Category', 'Product Name', 'Pack Type', 'Pack Size', 'VC Ideal Price', 'SC Ideal Price'] if c in list(h_asin.columns) + list(h_nc.columns) + list(h_nms.columns)]
    VENDOR_ONLY = ['Vendor Confirmation %', 'PO_received_amount', 'PO_received_Units', 'Receive_Fill_Rate', 'Overall Vendor Lead Time (days)', 'Aged 90+ Days Sellable Inventory', 'Aged 90+ Days Sellable Units', 'Sellable Inventory Amount', 'Unsellable On Hand Inventory Amount', 'Unsellable On Hand Units', 'Open POs']
    nc_raw = load_monthly_merged_files(NOON_INV_ROOT, MONTHS, 'merged_noon', 'NC')
    if not nc_raw.empty:
        nc_clean = standardise_noon_inv(nc_raw, 'Quantity', 'NC')
        if 'noon_rev_df' in dir() and (not noon_rev_df.empty):
            _nc_rev = noon_rev_df[['ASIN', 'Date', 'total_units']].rename(columns={'ASIN': 'NINs'})
        else:
            _nc_rev = pd.DataFrame(columns=['NINs', 'Date', 'total_units'])
        nc_clean = compute_l30_dos(nc_clean, _nc_rev, 'NINs', inventory_is_current=True)
        h_nc['NC_NIN'] = _clean_key(h_nc['NC_NIN'])
        nc_keys = set(nc_clean['NINs'].dropna())
        helper_nc_keys = set(h_nc['NC_NIN'].dropna())
        nc_clean = _apply_helper_map(nc_clean, h_nc, 'NC_NIN', 'NINs', INFO_COLS)
        nc_inv_df = nc_clean.rename(columns={'NINs': 'ASIN'}).copy()
        nc_inv_df['Sales Channel'] = 'Noon'
        for col in VENDOR_ONLY:
            if col not in nc_inv_df.columns:
                nc_inv_df[col] = 0
        nc_inv_df = nc_inv_df.sort_values(['ASIN', 'Date'])
    else:
        nc_inv_df = pd.DataFrame()
    nms_raw = load_monthly_merged_files(NMS_INV_ROOT, MONTHS, 'merged_nms', 'NMs')
    if not nms_raw.empty:
        nms_clean = standardise_noon_inv(nms_raw, 'Stock', 'NMs')
        if 'nms_rev_df' in dir() and (not nms_rev_df.empty):
            _nms_rev = nms_rev_df[['ASIN', 'Date', 'total_units']].rename(columns={'ASIN': 'NINs'})
        else:
            _nms_rev = pd.DataFrame(columns=['NINs', 'Date', 'total_units'])
        nms_clean = compute_l30_dos(nms_clean, _nms_rev, 'NINs', inventory_is_current=True)
        h_nms['NMs_NIN'] = _clean_key(h_nms['NMs_NIN'])
        nms_keys = set(nms_clean['NINs'].dropna())
        helper_nms_keys = set(h_nms['NMs_NIN'].dropna())
        nms_clean = _apply_helper_map(nms_clean, h_nms, 'NMs_NIN', 'NINs', INFO_COLS)
        nms_inv_df = nms_clean.rename(columns={'NINs': 'ASIN'}).copy()
        nms_inv_df['Sales Channel'] = 'Noon Minutes'
        for col in VENDOR_ONLY:
            if col not in nms_inv_df.columns:
                nms_inv_df[col] = 0
        nms_inv_df = nms_inv_df.sort_values(['ASIN', 'Date'])
    else:
        nms_inv_df = pd.DataFrame()
    if 'amz_inv_df' in dir() and (not amz_inv_df.empty):
        if 'Available Inventory' not in amz_inv_df.columns:
            pass
        else:
            amz_inv_df['ASIN'] = _clean_key(amz_inv_df['ASIN'].fillna(''))
            _amz_rev = pd.DataFrame()
            if 'amz_rev_df' in dir() and (not amz_rev_df.empty):
                _amz_rev = amz_rev_df[['ASIN', 'Date', 'total_units']].copy()
                _amz_rev['ASIN'] = _clean_key(_amz_rev['ASIN'].fillna(''))
            amz_inv_df.drop(columns=['Last 30 Days Sales', 'DOS', 'total_units'], inplace=True, errors='ignore')
            amz_inv_df = compute_l30_dos(amz_inv_df, _amz_rev, 'ASIN', inventory_is_current=False)
            h_asin['ASIN'] = _clean_key(h_asin['ASIN'])
            inventory_asins = set(amz_inv_df['ASIN'].dropna())
            helper_asins = set(h_asin['ASIN'].dropna())
            amz_inv_df = _apply_helper_map(amz_inv_df, h_asin, 'ASIN', 'ASIN', INFO_COLS)
            _t = amz_inv_df[amz_inv_df['ASIN'] == 'B0G64MSXJS']
            if not _t.empty:
                pass
    for _lbl, _df in [('Amazon        (Vendor Central)', amz_inv_df if 'amz_inv_df' in dir() else pd.DataFrame()), ('Noon Core     (NC)             ', nc_inv_df if 'nc_inv_df' in dir() else pd.DataFrame()), ('Noon Minutes  (NMs)            ', nms_inv_df if 'nms_inv_df' in dir() else pd.DataFrame())]:
        if _df is not None and (not _df.empty):
            _dates = pd.to_datetime(_df['Date'], errors='coerce').dropna()
            if 'DOS' in _df.columns:
                pass
            if 'Last 30 Days Sales' in _df.columns:
                pass
            if 'Available Inventory' in _df.columns:
                pass
            if 'Brand' in _df.columns:
                unk = (_df['Brand'] == 'Unknown').sum()

    def compute_dos_table(inventory_df, sales_df, key_col, inv_qty_col='Available Inventory', sales_qty_col='total_units'):
        """
        For every Key × inventory Date:
          1. Aggregate stock across all rows for that key/date.
          2. Calculate Last 30 Days Sales in window [T-2-29, T-2].
          3. Add any keys that had sales in the window but are missing from
             the inventory on that date (sold out / delisted) -> Inventory = 0.
          4. DOS = Inventory / (L30Sales / 30), 0 if no sales, capped at 3650.

        Returns: <key_col> | Date | Inventory | Last 30 Days Sales | DOS
        """
        if inventory_df is None or inventory_df.empty:
            return pd.DataFrame(columns=[key_col, 'Date', 'Inventory', 'Last 30 Days Sales', 'DOS'])
        inv = inventory_df[[key_col, 'Date', inv_qty_col]].copy()
        inv['Date'] = pd.to_datetime(inv['Date'], errors='coerce').dt.normalize()
        inv = inv[inv['Date'].notna()]
        inv = inv.groupby([key_col, 'Date'], as_index=False)[inv_qty_col].sum().rename(columns={inv_qty_col: 'Inventory'})
        if sales_df is not None and (not sales_df.empty) and (sales_qty_col in sales_df.columns):
            sales = sales_df[[key_col, 'Date', sales_qty_col]].copy()
            sales['Date'] = pd.to_datetime(sales['Date'], errors='coerce').dt.normalize()
            sales = sales[sales['Date'].notna()]
            sales[sales_qty_col] = pd.to_numeric(sales[sales_qty_col], errors='coerce').fillna(0)
        else:
            sales = pd.DataFrame(columns=[key_col, 'Date', sales_qty_col])
        all_inv_dates = sorted(inv['Date'].unique())
        records = []
        for inv_date in all_inv_dates:
            available_sales_dates = sales.loc[sales['Date'] <= inv_date, 'Date']
            if available_sales_dates.empty:
                continue
            t_end = available_sales_dates.max()
            t_start = t_end - pd.Timedelta(days=29)
            win_sales = sales[(sales['Date'] >= t_start) & (sales['Date'] <= t_end)]
            key_sales = win_sales.groupby(key_col)[sales_qty_col].sum().reset_index().rename(columns={sales_qty_col: 'L30Sales'})
            inv_today = inv[inv['Date'] == inv_date][[key_col, 'Inventory']].copy()
            merged = inv_today.merge(key_sales, on=key_col, how='outer')
            merged['Inventory'] = merged['Inventory'].fillna(0)
            merged['L30Sales'] = merged['L30Sales'].fillna(0)
            merged = merged[(merged['Inventory'] > 0) | (merged['L30Sales'] > 0)]
            for _, row in merged.iterrows():
                inventory = row['Inventory']
                l30 = row['L30Sales']
                daily_avg = l30 / 30
                dos = round(inventory / daily_avg, 1) if daily_avg > 0 else 0
                records.append({key_col: row[key_col], 'Date': inv_date, 'Inventory': inventory, 'Last 30 Days Sales': l30, 'DOS': dos})
        result = pd.DataFrame(records)
        if result.empty:
            return pd.DataFrame(columns=[key_col, 'Date', 'Inventory', 'Last 30 Days Sales', 'DOS'])
        result['DOS'] = pd.to_numeric(result['DOS'], errors='coerce').fillna(0).round(0).clip(upper=3650).astype('Int64')
        result = result.sort_values(['Date', key_col]).reset_index(drop=True)
        return result
    amz_dos_df = compute_dos_table(amz_inv_df, amz_rev_df, 'ASIN', inv_qty_col='Available Inventory', sales_qty_col='total_units') if 'amz_inv_df' in dir() and (not amz_inv_df.empty) else pd.DataFrame()
    noon_dos_df = compute_dos_table(nc_inv_df, noon_rev_df, 'ASIN', inv_qty_col='Available Inventory', sales_qty_col='total_units') if 'nc_inv_df' in dir() and (not nc_inv_df.empty) else pd.DataFrame()
    nms_dos_df = compute_dos_table(nms_inv_df, nms_rev_df, 'ASIN', inv_qty_col='Available Inventory', sales_qty_col='total_units') if 'nms_inv_df' in dir() and (not nms_inv_df.empty) else pd.DataFrame()

    def build_asin_priority_base(helper_df, helper_key_col, *signal_dfs):
        """
        helper_df       : h_asin / h_nc / h_nms  (one row per known ASIN/NIN)
        helper_key_col  : 'ASIN' / 'NC_NIN' / 'NMs_NIN'
        signal_dfs      : any number of DataFrames that each have a 'Date' col
                           (inventory_df, revenue_df, ads_df, ...) — every date
                           seen in ANY of them becomes a row for EVERY ASIN.

        Returns: ASIN | Date   (one row per known ASIN per known date)
        """
        asins = helper_df[[helper_key_col]].dropna().drop_duplicates().rename(columns={helper_key_col: 'ASIN'})
        asins['ASIN'] = asins['ASIN'].astype(str).str.upper().str.strip()
        asins = asins[asins['ASIN'] != ''].drop_duplicates()
        all_dates = set()
        for d in signal_dfs:
            if d is not None and (not d.empty) and ('Date' in d.columns):
                dates = pd.to_datetime(d['Date'], errors='coerce').dropna().dt.normalize()
                all_dates.update(dates.unique())
        if not all_dates:
            return pd.DataFrame(columns=['ASIN', 'Date'])
        dates_df = pd.DataFrame({'Date': sorted(all_dates)})
        base = asins.assign(_k=1).merge(dates_df.assign(_k=1), on='_k').drop(columns='_k')
        return base
    amz_asin_base = build_asin_priority_base(h_asin, 'ASIN', amz_inv_df, amz_rev_df, amz_ads_agg if 'amz_ads_agg' in dir() else None)
    nc_asin_base = build_asin_priority_base(h_nc, 'NC_NIN', nc_inv_df, noon_rev_df, noon_ads_agg if 'noon_ads_agg' in dir() else None)
    nms_asin_base = build_asin_priority_base(h_nms, 'NMs_NIN', nms_inv_df, nms_rev_df, nms_ads_agg if 'nms_ads_agg' in dir() else None)

    def add_metrics(asin_base, inv, rev_df, dos_df, channel=''):
        df = asin_base.copy()
        df['ASIN'] = df['ASIN'].astype(str).str.upper().str.strip()
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.normalize()
        df = df[df['Date'].notna()]
        if inv is not None and (not inv.empty):
            inv_clean = inv.copy()
            inv_clean = inv_clean.loc[:, ~inv_clean.columns.duplicated()]
            inv_clean['ASIN'] = inv_clean['ASIN'].astype(str).str.upper().str.strip()
            inv_clean['Date'] = pd.to_datetime(inv_clean['Date'], errors='coerce').dt.normalize()
            inv_clean = inv_clean[inv_clean['Date'].notna()]
            inv_clean = inv_clean.drop_duplicates(subset=['ASIN', 'Date'], keep='first')
            df = df.merge(inv_clean, on=['ASIN', 'Date'], how='left', suffixes=('', '_invsrc'))
            drop_dupe_cols = [c for c in df.columns if c.endswith('_invsrc')]
            if drop_dupe_cols:
                df.drop(columns=drop_dupe_cols, inplace=True)
        if 'Available Inventory' not in df.columns:
            df['Available Inventory'] = 0
        df['Available Inventory'] = pd.to_numeric(df['Available Inventory'], errors='coerce').fillna(0)
        if rev_df is not None and (not rev_df.empty):
            rev = rev_df.copy()
            rev['ASIN'] = rev['ASIN'].astype(str).str.upper().str.strip()
            rev['Date'] = pd.to_datetime(rev['Date'], errors='coerce').dt.normalize()
            keep_cols = [c for c in ['ASIN', 'Date', 'total_sales', 'total_units'] if c in rev.columns]
            rev = rev[keep_cols].drop_duplicates(subset=['ASIN', 'Date'])
            df = df.merge(rev, on=['ASIN', 'Date'], how='left')
        if 'total_sales' not in df.columns:
            df['total_sales'] = 0
        if 'total_units' not in df.columns:
            df['total_units'] = 0
        df['total_sales'] = pd.to_numeric(df['total_sales'], errors='coerce').fillna(0)
        df['total_units'] = pd.to_numeric(df['total_units'], errors='coerce').fillna(0).astype(int)
        df.drop(columns=['Last 30 Days Sales', 'DOS'], inplace=True, errors='ignore')
        if dos_df is not None and (not dos_df.empty):
            dos = dos_df.copy()
            dos['ASIN'] = dos['ASIN'].astype(str).str.upper().str.strip()
            dos['Date'] = pd.to_datetime(dos['Date'], errors='coerce').dt.normalize()
            dos = dos.drop_duplicates(subset=['ASIN', 'Date'], keep='first')
            dos = dos.rename(columns={'Inventory': '_dos_inventory'})
            df = df.merge(dos[['ASIN', 'Date', '_dos_inventory', 'Last 30 Days Sales', 'DOS']], on=['ASIN', 'Date'], how='left')
            df['Available Inventory'] = np.where(df['_dos_inventory'].notna(), df['_dos_inventory'], df['Available Inventory'])
            df.drop(columns=['_dos_inventory'], inplace=True, errors='ignore')
            df['Available Inventory'] = pd.to_numeric(df['Available Inventory'], errors='coerce').fillna(0)
        else:
            df['Last 30 Days Sales'] = 0.0
            df['DOS'] = 0
        df['Last 30 Days Sales'] = pd.to_numeric(df['Last 30 Days Sales'], errors='coerce').fillna(0)
        df['DOS'] = pd.to_numeric(df['DOS'], errors='coerce').fillna(0).round(0).clip(upper=3650).astype('Int64')
        df['sell_through'] = np.where(df['Last 30 Days Sales'] > 0, df['Last 30 Days Sales'] / 30, 0)
        df['sell_through'] = pd.to_numeric(df['sell_through'], errors='coerce').fillna(0).round(4)
        today_dt = date.today()

        def calc_oos(group):
            group = group.sort_values('Date').copy()
            current_month_df = group[(group['Date'].dt.month == today_dt.month) & (group['Date'].dt.year == today_dt.year)]
            if current_month_df.empty:
                return pd.Series(['Instock'] * len(group), index=group.index)
            latest = current_month_df.iloc[-1]
            if latest['Available Inventory'] == 0:
                prev_stock = current_month_df[(current_month_df['Date'] < latest['Date']) & (current_month_df['Available Inventory'] > 0)]
                if not prev_stock.empty:
                    oos_date = prev_stock.iloc[-1]['Date'] + pd.Timedelta(days=1)
                else:
                    oos_date = current_month_df.iloc[0]['Date']
            else:
                st = latest['sell_through']
                if pd.notna(st) and st > 0:
                    projected_days = int(latest['Available Inventory'] / st)
                    if projected_days > 3650:
                        projected_days = 3650
                    oos_date = latest['Date'] + pd.Timedelta(days=projected_days)
                else:
                    oos_date = 'Instock'
            return pd.Series([oos_date] * len(group), index=group.index)
        df['OOS Date'] = df.groupby('ASIN', group_keys=False).apply(calc_oos)
        df['min_available_qty'] = (df['sell_through'] * 30).round(2)
        df['max_available_qty'] = (df['sell_through'] * 60).round(2)
        conditions = [(df['Available Inventory'] > df['min_available_qty']) & (df['Available Inventory'] <= df['max_available_qty']), df['Available Inventory'] > df['max_available_qty'], df['Available Inventory'] <= df['min_available_qty']]
        choices = ['Healthy', 'Overstock', 'Understock']
        df['Stock_Status'] = np.select(conditions, choices, default='Unknown')
        if 'Open POs' not in df.columns:
            df['Open POs'] = 0
        df['Open POs'] = pd.to_numeric(df['Open POs'], errors='coerce').fillna(0)
        df['No/Low Stock wt Open POs'] = ((df['Stock_Status'] == 'Understock') & (df['Open POs'] > 0)).astype(int)
        df['No/Low Stock wt no Open POs'] = ((df['Stock_Status'] == 'Understock') & (df['Open POs'] <= 0)).astype(int)
        df = df.sort_values(['ASIN', 'Date'])
        df['year_month'] = df['Date'].dt.to_period('M')
        df['in_stock_flag'] = (df['Available Inventory'] > 0).astype(int)
        df['cumulative_instock_days'] = df.groupby(['ASIN', 'year_month'])['in_stock_flag'].cumsum()
        df['day_of_month'] = df['Date'].dt.day
        df['Instock Rate'] = (df['cumulative_instock_days'] / df['day_of_month'] * 100).round(2)
        df.drop(columns=['year_month'], inplace=True)
        df['Sales Channel'] = channel
        df = df.drop_duplicates(subset=['ASIN', 'Date'], keep='first')
        df = df.sort_values(['ASIN', 'Date'])
        return df
    amz_inv_final = add_metrics(amz_asin_base, amz_inv_df, amz_rev_df, amz_dos_df, 'Vendor Central')
    nms_inv_final = add_metrics(nms_asin_base, nms_inv_df, nms_rev_df, nms_dos_df, 'Noon Minutes')
    nc_inv_final = add_metrics(nc_asin_base, nc_inv_df, noon_rev_df, noon_dos_df, 'Noon')
    amz_inv_final = _apply_helper_map(amz_inv_final, h_asin, 'ASIN', 'ASIN', INFO_COLS)
    nc_inv_final = _apply_helper_map(nc_inv_final, h_nc, 'NC_NIN', 'ASIN', INFO_COLS)
    nms_inv_final = _apply_helper_map(nms_inv_final, h_nms, 'NMs_NIN', 'ASIN', INFO_COLS)

    def align_cols(df, cols):
        if df is None or df.empty:
            return pd.DataFrame(columns=cols)
        out = df.copy()
        out = out.loc[:, ~out.columns.duplicated()]
        for col in cols:
            if col not in out.columns:
                out[col] = np.nan
        out = out[cols].copy()
        return out
    INVENTORY_COLS = ['ASIN', 'Brand', 'Product Category', 'Product Sub Category', 'Product Name', 'Pack Type', 'Pack Size', 'SC Ideal Price', 'VC Ideal Price', 'Available Inventory', 'Sellable Inventory Amount', 'Unsellable On Hand Inventory Amount', 'Unsellable On Hand Units', 'Vendor Confirmation %', 'PO_received_amount', 'PO_received_Units', 'Open POs', 'Receive_Fill_Rate', 'Overall Vendor Lead Time (days)', 'Aged 90+ Days Sellable Inventory', 'Aged 90+ Days Sellable Units', 'Date', 'Sales Channel', 'in_stock_flag', 'cumulative_instock_days', 'day_of_month', 'Instock Rate', 'total_sales', 'total_units', 'sell_through', 'Last 30 Days Sales', 'DOS', 'OOS Date', 'min_available_qty', 'max_available_qty', 'Stock_Status', 'No/Low Stock wt Open POs', 'No/Low Stock wt no Open POs']
    inventory_output = pd.concat([align_cols(amz_inv_final, INVENTORY_COLS), align_cols(nms_inv_final, INVENTORY_COLS), align_cols(nc_inv_final, INVENTORY_COLS)], ignore_index=True)
    inventory_output = inventory_output.drop_duplicates(subset=['ASIN', 'Date', 'Sales Channel'], keep='first')
    inventory_output['Date'] = pd.to_datetime(inventory_output['Date'], errors='coerce').dt.normalize()
    if 'Brand' in inventory_output.columns:
        inventory_output['Brand'] = inventory_output['Brand'].replace('', np.nan).fillna('Emami')
    text_cols = ['Product Category', 'Product Sub Category', 'Product Name', 'Pack Type', 'Stock_Status']
    for col in text_cols:
        if col in inventory_output.columns:
            inventory_output[col] = inventory_output[col].replace('', np.nan).fillna('Unknown')
    numeric_cols = inventory_output.select_dtypes(include=['float', 'int', 'Int64']).columns
    inventory_output[numeric_cols] = inventory_output[numeric_cols].fillna(0)
    inventory_output = inventory_output.sort_values(['Sales Channel', 'ASIN', 'Date'])
    inventory_output = inventory_output.reset_index(drop=True)

    def apply_helper(df):
        INFO_COLS_LOCAL = ['Brand', 'Product Category', 'Product Sub Category', 'Product Name', 'Pack Type', 'Pack Size', 'VC Ideal Price', 'SC Ideal Price']
        INFO_COLS_LOCAL = [c for c in INFO_COLS_LOCAL if c in h_asin.columns or c in h_nc.columns or c in h_nms.columns]
        out = df.copy()

        def _clean_asin_for_channel(row):
            s = str(row['ASIN']).upper().strip().replace('\xa0', '').replace('.0', '')
            import re as _re
            s = _re.sub('\\s+', '', s)
            if row.get('Sales Channel') == 'Vendor Central':
                s = _re.sub('-\\d+$', '', s)
            return s
        out['ASIN'] = out.apply(_clean_asin_for_channel, axis=1)
        cols_to_drop = [c for c in INFO_COLS_LOCAL if c in out.columns]
        out.drop(columns=cols_to_drop, inplace=True, errors='ignore')
        amz_mask = out['Sales Channel'] == 'Vendor Central'
        nms_mask = out['Sales Channel'] == 'Noon Minutes'
        nc_mask = out['Sales Channel'] == 'Noon'
        amz = out[amz_mask].copy()
        nms = out[nms_mask].copy()
        nc = out[nc_mask].copy()
        other = out[~(amz_mask | nms_mask | nc_mask)].copy()
        if not amz.empty and (not h_asin.empty):
            h = h_asin[[c for c in ['ASIN'] + INFO_COLS_LOCAL if c in h_asin.columns]].copy()
            amz = amz.merge(h, on='ASIN', how='left')
        if not nc.empty and (not h_nc.empty):
            h = h_nc[[c for c in ['NC_NIN'] + INFO_COLS_LOCAL if c in h_nc.columns]].copy()
            nc = nc.merge(h, left_on='ASIN', right_on='NC_NIN', how='left')
            nc.drop(columns=['NC_NIN'], inplace=True, errors='ignore')
        if not nms.empty and (not h_nms.empty):
            h = h_nms[[c for c in ['NMs_NIN'] + INFO_COLS_LOCAL if c in h_nms.columns]].copy()
            nms = nms.merge(h, left_on='ASIN', right_on='NMs_NIN', how='left')
            nms.drop(columns=['NMs_NIN'], inplace=True, errors='ignore')
        final = pd.concat([amz, nms, nc, other], ignore_index=True)
        for col in list(final.columns):
            if col.endswith('_x'):
                base = col[:-2]
                y_col = base + '_y'
                final[base] = final[col].combine_first(final.get(y_col))
                final.drop(columns=[col, y_col], inplace=True, errors='ignore')
        text_info = ['Brand', 'Product Category', 'Product Sub Category', 'Product Name', 'Pack Type']
        for col in text_info:
            if col not in final.columns:
                final[col] = 'Unknown'
            final[col] = final[col].fillna('Unknown')
        if 'Brand' in final.columns:
            final['Brand'] = final['Brand'].replace('', 'Unknown').replace('Unknown', 'Emami')
        num_info = ['Pack Size', 'VC Ideal Price', 'SC Ideal Price']
        for col in num_info:
            if col not in final.columns:
                final[col] = 0
            final[col] = pd.to_numeric(final[col], errors='coerce').fillna(0)
        return final
    inventory_output = apply_helper(inventory_output)
    filled = (inventory_output['Product Category'] != 'Unknown').sum()
    rename_columns = {'ASIN': 'asin', 'Available Inventory': 'available_inventory', 'Sellable Inventory Amount': 'sellable_inventory_amount', 'Unsellable On Hand Inventory Amount': 'unsellable_on_hand_inventory_amount', 'Unsellable On Hand Units': 'unsellable_on_hand_units', 'Vendor Confirmation %': 'vendor_confirmation_pct', 'PO_received_amount': 'po_received_amount', 'PO_received_Units': 'po_received_units', 'Open Pos': 'open_pos', 'Open POs': 'open_pos', 'Receive_Fill_Rate': 'receive_fill_rate', 'Overall Vendor Lead Time (days)': 'overall_vendor_lead_time_days', 'Aged 90+ Days Sellable Inventory': 'aged_90_plus_days_sellable_inventory', 'Aged 90+ Days Sellable Units': 'aged_90_plus_days_sellable_units', 'Date': 'date', 'Sales Channel': 'sales_channel', 'Instock Rate': 'instock_rate', 'Last 30 Days Sales': 'units_shipped_t30', 'DOS': 'dos', 'OOS Date': 'oos_date', 'Stock_Status': 'stock_status', 'No/Low Stock wt Open Pos': 'no_low_stock_wt_open_pos', 'No/Low Stock wt Open POs': 'no_low_stock_wt_open_pos', 'No/Low Stock wt no Open Pos': 'no_low_stock_wt_no_open_pos', 'No/Low Stock wt no Open POs': 'no_low_stock_wt_no_open_pos', 'Brand': 'brand', 'Product Category': 'product_category', 'Product Sub Category': 'product_sub_category', 'Product Name': 'product_name', 'Pack Type': 'pack_type', 'Pack Size': 'pack_size', 'VC Ideal Price': 'vc_ideal_price', 'SC Ideal Price': 'sc_ideal_price'}
    inventory_output.rename(columns=rename_columns, inplace=True)
    required_columns = ['sku', 'fnsku', 'asin', 'condition', 'your_price', 'mfn_listing_exists', 'mfn_fulfillable_quantity', 'afn_listing_exists', 'afn_warehouse_quantity', 'afn_fulfillable_quantity', 'afn_unsellable_quantity', 'afn_reserved_quantity', 'afn_total_quantity', 'per_unit_volume', 'afn_inbound_working_quantity', 'afn_inbound_shipped_quantity', 'afn_inbound_receiving_quantity', 'afn_researching_quantity', 'afn_reserved_future_supply', 'afn_future_supply_buyable', 'store', 'date', 'reserved_qty', 'reserved_customerorders', 'reserved_fc_transfers', 'reserved_fc_processing', 'available_inventory', 'units_shipped_t30', 'units_shipped_t60', 'units_shipped_t90', 'open_pos', 'sell_through', 'dos', 'min_available_qty', 'max_available_qty', 'stock_status', 'instock_rate', 'no_low_stock_wt_open_pos', 'no_low_stock_wt_no_open_pos', 'total_sales', 'total_units', 'product_name', 'product_category', 'pack_type', 'pack_size', 'sc_ideal_price', 'vc_ideal_price', 'sales_channel', 'brand', 'product_sub_category', 'vendor_confirmation_pct', 'po_received_amount', 'po_received_units', 'receive_fill_rate', 'overall_vendor_lead_time_days', 'aged_90_plus_days_sellable_inventory', 'aged_90_plus_days_sellable_units', 'sellable_inventory_amount', 'unsellable_on_hand_inventory_amount', 'unsellable_on_hand_units', 'in_stock_flag', 'cumulative_instock_days', 'day_of_month', 'oos_date']
    text_columns = ['sku', 'fnsku', 'asin', 'condition', 'store', 'product_name', 'product_category', 'pack_type', 'pack_size', 'sales_channel', 'brand', 'product_sub_category', 'stock_status', 'oos_date']
    missing_columns = []
    for col in required_columns:
        if col not in inventory_output.columns:
            missing_columns.append(col)
            if col in text_columns:
                inventory_output[col] = ''
            else:
                inventory_output[col] = 0
    extra_columns = [col for col in inventory_output.columns if col not in required_columns]
    inventory_output = inventory_output[required_columns + extra_columns]

    def build_revenue_channel(inv_final, ads_agg):
        df = inv_final.copy()
        df = df.loc[:, ~df.columns.duplicated()]
        df['ASIN'] = df['ASIN'].astype(str).str.upper().str.strip()
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.normalize()
        if ads_agg is not None and (not ads_agg.empty):
            ads = ads_agg.copy()
            ads = ads.loc[:, ~ads.columns.duplicated()]
            keep_cols = ['ASIN', 'Date', 'Sales Channel', 'ads_sales', 'ads_unit_sold', 'ads_spend']
            keep_cols = [c for c in keep_cols if c in ads.columns]
            ads = ads[keep_cols]
            ads['ASIN'] = ads['ASIN'].astype(str).str.upper().str.strip()
            ads['Date'] = pd.to_datetime(ads['Date'], errors='coerce').dt.normalize()
            for col in ['ads_sales', 'ads_unit_sold', 'ads_spend']:
                if col in ads.columns:
                    ads[col] = pd.to_numeric(ads[col], errors='coerce').fillna(0)
            ads = ads.drop_duplicates(subset=['ASIN', 'Date', 'Sales Channel'])
            merge_keys = ['ASIN', 'Date']
            if 'Sales Channel' in ads.columns:
                merge_keys.append('Sales Channel')
            df = df.merge(ads, on=merge_keys, how='left')
        for col in ['ads_sales', 'ads_unit_sold', 'ads_spend']:
            if col not in df.columns:
                df[col] = 0
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df['organic_sale'] = df['total_sales'] - df['ads_sales']
        df['organic_sale'] = df['organic_sale'].clip(lower=0).round(2)
        df = df.sort_values(['Sales Channel', 'ASIN', 'Date'])
        return df
    amz_rev_final = build_revenue_channel(amz_inv_final, amz_ads_agg)
    nc_rev_final = build_revenue_channel(nc_inv_final, noon_ads_agg)
    nms_rev_final = build_revenue_channel(nms_inv_final, nms_ads_agg)
    REVENUE_COLS = INVENTORY_COLS + ['ads_sales', 'ads_unit_sold', 'ads_spend', 'organic_sale']
    revenue_output = pd.concat([align_cols(amz_rev_final, REVENUE_COLS), align_cols(nc_rev_final, REVENUE_COLS), align_cols(nms_rev_final, REVENUE_COLS)], ignore_index=True)
    revenue_output = revenue_output.drop_duplicates(subset=['ASIN', 'Date', 'Sales Channel'], keep='first')
    revenue_output['Date'] = pd.to_datetime(revenue_output['Date'], errors='coerce').dt.normalize()
    text_cols = ['Brand', 'Product Category', 'Product Sub Category', 'Product Name', 'Pack Type', 'Stock_Status']
    for col in text_cols:
        if col in revenue_output.columns:
            revenue_output[col] = revenue_output[col].replace('', np.nan).fillna('Unknown')
    numeric_cols = revenue_output.select_dtypes(include=['float', 'int', 'Int64']).columns
    revenue_output[numeric_cols] = revenue_output[numeric_cols].fillna(0)
    revenue_output = revenue_output.sort_values(['Sales Channel', 'ASIN', 'Date'])
    revenue_output = revenue_output.reset_index(drop=True)
    _rev_checksum_pairs = [('Vendor Central', amz_ads_agg), ('Noon', noon_ads_agg), ('Noon Minutes', nms_ads_agg)]
    for _channel_name, _agg_df in _rev_checksum_pairs:
        if _agg_df is None or _agg_df.empty:
            continue
        _pre_total = pd.to_numeric(_agg_df.get('ads_sales', 0), errors='coerce').fillna(0).sum()
        _post_total = pd.to_numeric(revenue_output.loc[revenue_output['Sales Channel'] == _channel_name, 'ads_sales'], errors='coerce').fillna(0).sum()
        _diff = _pre_total - _post_total
        flag = '⚠️ MISMATCH' if abs(_diff) > 0.01 else '✅ OK'
    rename_columns = {'ASIN': 'asin', 'Brand': 'brand', 'Product Category': 'product_category', 'Product Sub Category': 'product_sub_category', 'Product Name': 'product_name', 'Pack Type': 'pack_type', 'Pack Size': 'pack_size', 'SC Ideal Price': 'sc_ideal_price', 'VC Ideal Price': 'vc_ideal_price', 'Available Inventory': 'available_inventory', 'Sellable Inventory Amount': 'sellable_inventory_amount', 'Unsellable On Hand Inventory Amount': 'unsellable_on_hand_inventory_amount', 'Unsellable On Hand Units': 'unsellable_on_hand_units', 'Vendor Confirmation %': 'vendor_confirmation_pct', 'PO_received_amount': 'po_received_amount', 'PO_received_Units': 'po_received_units', 'Open Pos': 'open_pos', 'Open POs': 'open_pos', 'Receive_Fill_Rate': 'receive_fill_rate', 'Overall Vendor Lead Time (days)': 'overall_vendor_lead_time_days', 'Aged 90+ Days Sellable Inventory': 'aged_90_plus_days_sellable_inventory', 'Aged 90+ Days Sellable Units': 'aged_90_plus_days_sellable_units', 'Date': 'date', 'Sales Channel': 'sales_channel', 'Instock Rate': 'instock_rate', 'Last 30 Days Sales': 'units_shipped_t30', 'DOS': 'dos', 'OOS Date': 'oos_date', 'Stock_Status': 'stock_status', 'No/Low Stock wt Open Pos': 'no_low_stock_wt_open_pos', 'No/Low Stock wt Open POs': 'no_low_stock_wt_open_pos', 'No/Low Stock wt no Open Pos': 'no_low_stock_wt_no_open_pos', 'No/Low Stock wt no Open POs': 'no_low_stock_wt_no_open_pos'}
    revenue_output.rename(columns=rename_columns, inplace=True)
    required_columns = ['asin', 'brand', 'product_sub_category', 'vendor_confirmation_pct', 'po_received_amount', 'po_received_units', 'open_pos', 'receive_fill_rate', 'overall_vendor_lead_time_days', 'aged_90_plus_days_sellable_inventory', 'aged_90_plus_days_sellable_units', 'sellable_inventory_amount', 'available_inventory', 'unsellable_on_hand_inventory_amount', 'unsellable_on_hand_units', 'date', 'sales_channel', 'in_stock_flag', 'cumulative_instock_days', 'day_of_month', 'instock_rate', 'total_sales', 'total_units', 'sell_through', 'dos', 'oos_date', 'min_available_qty', 'max_available_qty', 'stock_status', 'no_low_stock_wt_open_pos', 'no_low_stock_wt_no_open_pos', 'ads_sales', 'ads_unit_sold', 'ads_spend', 'product_name', 'product_category', 'pack_type', 'pack_size', 'sc_ideal_price', 'vc_ideal_price', 'sku', 'fnsku', 'condition', 'your_price', 'mfn_listing_exists', 'mfn_fulfillable_quantity', 'afn_listing_exists', 'afn_warehouse_quantity', 'afn_fulfillable_quantity', 'afn_unsellable_quantity', 'afn_reserved_quantity', 'afn_total_quantity', 'per_unit_volume', 'afn_inbound_working_quantity', 'afn_inbound_shipped_quantity', 'afn_inbound_receiving_quantity', 'afn_researching_quantity', 'afn_reserved_future_supply', 'afn_future_supply_buyable', 'store', 'reserved_qty', 'reserved_customerorders', 'reserved_fc_transfers', 'reserved_fc_processing', 'units_shipped_t30', 'units_shipped_t60', 'units_shipped_t90']
    text_columns = ['asin', 'brand', 'product_sub_category', 'sales_channel', 'product_name', 'product_category', 'pack_type', 'pack_size', 'stock_status', 'oos_date', 'sku', 'fnsku', 'condition', 'store']
    missing_columns = []
    for col in required_columns:
        if col not in revenue_output.columns:
            missing_columns.append(col)
            if col in text_columns:
                revenue_output[col] = ''
            else:
                revenue_output[col] = 0
    for col in missing_columns:
        pass
    extra_columns = [col for col in revenue_output.columns if col not in required_columns]
    revenue_output = revenue_output[required_columns + extra_columns]

    def build_marketing(inv_final, ads_campaign, channel):
        df = inv_final.copy()
        df = df.loc[:, ~df.columns.duplicated()]
        df['ASIN'] = df['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.normalize()
        df['Sales Channel'] = channel
        if ads_campaign is not None and (not ads_campaign.empty):
            a = ads_campaign.copy()
            a = a.loc[:, ~a.columns.duplicated()]
            a['ASIN'] = a['ASIN'].astype(str).str.upper().str.strip().str.replace('.0', '', regex=False)
            a['Date'] = pd.to_datetime(a['Date'], errors='coerce').dt.normalize()
            if 'Sales Channel' not in a.columns:
                a['Sales Channel'] = channel
            numeric_ads_cols = ['ads_sales', 'ads_unit_sold', 'ads_spend', 'Impressions', 'Clicks', 'Click-Thru Rate (CTR)', 'Cost Per Click (CPC)', 'Total Advertising Cost of Sales (ACOS)', 'Total Return on Advertising Spend (ROAS)', 'CVR']
            for col in numeric_ads_cols:
                if col in a.columns:
                    a[col] = pd.to_numeric(a[col], errors='coerce').fillna(0)
            keep_cols = ['ASIN', 'Date', 'Sales Channel', 'ads_sales', 'ads_unit_sold', 'ads_spend', 'Impressions', 'Clicks', 'Click-Thru Rate (CTR)', 'Cost Per Click (CPC)', 'Total Advertising Cost of Sales (ACOS)', 'Total Return on Advertising Spend (ROAS)', 'CVR', 'Campaign Name', 'Ad Group Name', 'Campaign Type', 'Portfolio name']
            keep_cols = [c for c in keep_cols if c in a.columns]
            a = a[keep_cols]
            dedup_subset = [c for c in ['ASIN', 'Date', 'Sales Channel', 'Campaign Name', 'Ad Group Name', 'Campaign Type'] if c in a.columns]
            before_dedup_rows = len(a)
            before_dedup_sales = pd.to_numeric(a.get('ads_sales', 0), errors='coerce').fillna(0).sum()
            a = a.drop_duplicates(subset=dedup_subset, keep='first')
            after_dedup_sales = pd.to_numeric(a.get('ads_sales', 0), errors='coerce').fillna(0).sum()
            if abs(before_dedup_sales - after_dedup_sales) > 0.01:
                pass
            sum_cols = ['ads_sales', 'ads_unit_sold', 'ads_spend', 'Impressions', 'Clicks', 'CVR']
            mean_cols = ['Click-Thru Rate (CTR)', 'Cost Per Click (CPC)', 'Total Advertising Cost of Sales (ACOS)', 'Total Return on Advertising Spend (ROAS)']
            text_cols_ads = ['Campaign Name', 'Ad Group Name', 'Campaign Type', 'Portfolio name']
            agg_dict = {}
            for c in sum_cols:
                if c in a.columns:
                    agg_dict[c] = 'sum'
            for c in mean_cols:
                if c in a.columns:
                    agg_dict[c] = 'mean'
            for c in text_cols_ads:
                if c in a.columns:
                    agg_dict[c] = lambda x: ' | '.join(x.dropna().astype(str).unique())
            if agg_dict:
                a_agg = a.groupby(['ASIN', 'Date', 'Sales Channel'], as_index=False).agg(agg_dict)
            else:
                a_agg = a.drop_duplicates(subset=['ASIN', 'Date', 'Sales Channel'])
            df = df.merge(a_agg, on=['ASIN', 'Date', 'Sales Channel'], how='left')
        ads_cols = ['ads_sales', 'ads_unit_sold', 'ads_spend', 'Impressions', 'Clicks', 'Click-Thru Rate (CTR)', 'Cost Per Click (CPC)', 'Total Advertising Cost of Sales (ACOS)', 'Total Return on Advertising Spend (ROAS)', 'CVR']
        for col in ads_cols:
            if col not in df.columns:
                df[col] = 0
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        text_cols = ['Campaign Name', 'Ad Group Name', 'Campaign Type', 'Portfolio name']
        for col in text_cols:
            if col not in df.columns:
                df[col] = ''
            df[col] = df[col].fillna('')
        df['organic_sale'] = df['total_sales'] - df['ads_sales']
        df['organic_sale'] = df['organic_sale'].clip(lower=0).round(2)
        df = df.sort_values(['Sales Channel', 'ASIN', 'Date'])
        return df
    amz_mkt_final = build_marketing(amz_inv_final, amz_ads_campaign, 'Vendor Central')
    nms_mkt_final = build_marketing(nms_inv_final, nms_ads_campaign, 'Noon Minutes')
    nc_mkt_final = build_marketing(nc_inv_final, noon_ads_campaign, 'Noon')
    MARKETING_COLS = INVENTORY_COLS + ['ads_sales', 'ads_unit_sold', 'ads_spend', 'organic_sale', 'Impressions', 'Clicks', 'Click-Thru Rate (CTR)', 'Cost Per Click (CPC)', 'Total Advertising Cost of Sales (ACOS)', 'Total Return on Advertising Spend (ROAS)', 'CVR', 'Campaign Name', 'Campaign Type', 'Portfolio name']
    marketing_output = pd.concat([align_cols(amz_mkt_final, MARKETING_COLS), align_cols(nms_mkt_final, MARKETING_COLS), align_cols(nc_mkt_final, MARKETING_COLS)], ignore_index=True)
    before_final_dedup_sales = pd.to_numeric(marketing_output.get('ads_sales', 0), errors='coerce').fillna(0).sum()
    marketing_output = marketing_output.drop_duplicates(subset=['ASIN', 'Date', 'Sales Channel'], keep='first')
    after_final_dedup_sales = pd.to_numeric(marketing_output.get('ads_sales', 0), errors='coerce').fillna(0).sum()
    if abs(before_final_dedup_sales - after_final_dedup_sales) > 0.01:
        pass
    marketing_output['Date'] = pd.to_datetime(marketing_output['Date'], errors='coerce').dt.normalize()
    text_fill_cols = ['Brand', 'Product Category', 'Product Sub Category', 'Product Name', 'Pack Type', 'Campaign Name', 'Campaign Type', 'Portfolio name']
    for col in text_fill_cols:
        if col in marketing_output.columns:
            marketing_output[col] = marketing_output[col].replace('', np.nan).fillna('Unknown')
    numeric_cols = marketing_output.select_dtypes(include=['float', 'int', 'Int64']).columns
    marketing_output[numeric_cols] = marketing_output[numeric_cols].fillna(0)
    marketing_output = marketing_output.sort_values(['Sales Channel', 'ASIN', 'Date'])
    marketing_output = marketing_output.reset_index(drop=True)
    _checksum_pairs = [('Vendor Central', amz_ads_campaign), ('Noon Minutes', nms_ads_campaign), ('Noon', noon_ads_campaign)]
    for _channel_name, _campaign_df in _checksum_pairs:
        if _campaign_df is None or _campaign_df.empty:
            continue
        _pre_total = pd.to_numeric(_campaign_df.get('ads_sales', 0), errors='coerce').fillna(0).sum()
        _post_total = pd.to_numeric(marketing_output.loc[marketing_output['Sales Channel'] == _channel_name, 'ads_sales'], errors='coerce').fillna(0).sum()
        _diff = _pre_total - _post_total
        flag = '⚠️ MISMATCH' if abs(_diff) > 0.01 else '✅ OK'
    rename_columns = {'ASIN': 'asin', 'Brand': 'brand', 'Product Category': 'product_category', 'Product Sub Category': 'product_sub_category', 'Product Name': 'product_name', 'Pack Type': 'pack_type', 'Pack Size': 'pack_size', 'SC Ideal Price': 'sc_ideal_price', 'VC Ideal Price': 'vc_ideal_price', 'CVR': 'cvr', 'Available Inventory': 'available_inventory', 'Sellable Inventory Amount': 'sellable_inventory_amount', 'Unsellable On Hand Inventory Amount': 'unsellable_on_hand_inventory_amount', 'Unsellable On Hand Units': 'unsellable_on_hand_units', 'Vendor Confirmation %': 'vendor_confirmation_pct', 'PO_received_amount': 'po_received_amount', 'PO_received_Units': 'po_received_units', 'Open Pos': 'open_pos', 'Open POs': 'open_pos', 'Receive_Fill_Rate': 'receive_fill_rate', 'Overall Vendor Lead Time (days)': 'overall_vendor_lead_time_days', 'Aged 90+ Days Sellable Inventory': 'aged_90_plus_days_sellable_inventory', 'Aged 90+ Days Sellable Units': 'aged_90_plus_days_sellable_units', 'Date': 'date', 'Sales Channel': 'sales_channel', 'Instock Rate': 'instock_rate', 'Last 30 Days Sales': 'units_shipped_t30', 'DOS': 'dos', 'OOS Date': 'oos_date', 'Stock_Status': 'stock_status', 'No/Low Stock wt Open Pos': 'no_low_stock_wt_no_open_pos', 'No/Low Stock wt Open POs': 'no_low_stock_wt_open_pos', 'No/Low Stock wt no Open Pos': 'no_low_stock_wt_no_open_pos', 'No/Low Stock wt no Open POs': 'no_low_stock_wt_no_open_pos', 'Impressions': 'impressions', 'Clicks': 'clicks', 'Click-Thru Rate (CTR)': 'click_thru_rate_ctr', 'Cost Per Click (CPC)': 'cost_per_click_cpc', 'Total Advertising Cost of Sales (ACOS)': 'total_advertising_cost_of_sales_acos', 'Total Return on Advertising Spend (ROAS)': 'total_return_on_advertising_spend_roas', 'Campaign Name': 'campaign_name', 'Campaign Type': 'campaign_type', 'Portfolio name': 'portfolio_name'}
    marketing_output.rename(columns=rename_columns, inplace=True)
    required_columns = ['sku', 'fnsku', 'asin', 'condition', 'your_price', 'mfn_listing_exists', 'mfn_fulfillable_quantity', 'afn_listing_exists', 'afn_warehouse_quantity', 'afn_fulfillable_quantity', 'afn_unsellable_quantity', 'afn_reserved_quantity', 'afn_total_quantity', 'per_unit_volume', 'afn_inbound_working_quantity', 'afn_inbound_shipped_quantity', 'afn_inbound_receiving_quantity', 'afn_researching_quantity', 'afn_reserved_future_supply', 'afn_future_supply_buyable', 'store', 'date', 'reserved_qty', 'reserved_customerorders', 'reserved_fc_transfers', 'reserved_fc_processing', 'available_inventory', 'units_shipped_t30', 'units_shipped_t60', 'units_shipped_t90', 'open_pos', 'sell_through', 'dos', 'min_available_qty', 'max_available_qty', 'stock_status', 'instock_rate', 'no_low_stock_wt_open_pos', 'no_low_stock_wt_no_open_pos', 'total_sales', 'total_units', 'sales_channel', 'brand', 'ads_sales', 'ads_unit_sold', 'ads_spend', 'impressions', 'clicks', 'click_thru_rate_ctr', 'cost_per_click_cpc', 'total_advertising_cost_of_sales_acos', 'total_return_on_advertising_spend_roas', 'cvr', 'campaign_name', 'campaign_type', 'portfolio_name', 'product_name', 'product_category', 'pack_type', 'pack_size', 'sc_ideal_price', 'vc_ideal_price', 'product_sub_category', 'vendor_confirmation_pct', 'po_received_amount', 'po_received_units', 'receive_fill_rate', 'overall_vendor_lead_time_days', 'aged_90_plus_days_sellable_inventory', 'aged_90_plus_days_sellable_units', 'sellable_inventory_amount', 'unsellable_on_hand_inventory_amount', 'unsellable_on_hand_units', 'in_stock_flag', 'cumulative_instock_days', 'day_of_month', 'oos_date']
    text_columns = ['sku', 'fnsku', 'asin', 'condition', 'store', 'sales_channel', 'brand', 'campaign_name', 'campaign_type', 'portfolio_name', 'product_name', 'product_category', 'product_sub_category', 'pack_type', 'pack_size', 'stock_status', 'oos_date']
    missing_columns = []
    for col in required_columns:
        if col not in marketing_output.columns:
            missing_columns.append(col)
            if col in text_columns:
                marketing_output[col] = ''
            else:
                marketing_output[col] = 0
    for col in missing_columns:
        pass
    extra_columns = [col for col in marketing_output.columns if col not in required_columns]
    marketing_output = marketing_output[required_columns + extra_columns]
    standard_cols = ['date', 'time', 'region', 'asin', 'buybox', 'link', 'product_name', 'rating', 'reviews', 'bsr_main', 'bsr_sub', 'price', 'sold_by', 'moq']
    dfs = []
    base_month_path = str(config.buybox_history_root)
    if os.path.isdir(base_month_path):
        for month_folder in os.listdir(base_month_path):
            month_path = os.path.join(base_month_path, month_folder)
            if not os.path.isdir(month_path):
                continue
            for day_folder in os.listdir(month_path):
                day_path = os.path.join(month_path, day_folder)
                if not os.path.isdir(day_path):
                    continue
                for file in os.listdir(day_path):
                    if not file.endswith('.xlsx'):
                        continue
                    fp = os.path.join(day_path, file)
                    try:
                        df = pd.read_excel(fp)
                        df.columns = df.columns.str.lower().str.strip()
                        df.rename(columns={'title': 'product_name', 'seller': 'sold_by', 'type': 'buybox'}, inplace=True)
                        if 'buybox' in df.columns:
                            df['buybox'] = df['buybox'].astype(str).str.lower().replace({'yes': 'YES', 'main': 'YES'}).apply(lambda x: 'YES' if x == 'YES' else 'NO')
                        else:
                            df['buybox'] = 'NO'
                        if 'region' not in df.columns:
                            df['region'] = 'AE'
                        if 'moq' in df.columns:
                            df['moq'] = df['moq'].astype(str).str.extract('(\\d+)')[0].fillna('1')
                        else:
                            df['moq'] = '1'
                        if 'price' in df.columns:
                            df['price'] = pd.to_numeric(df['price'], errors='coerce')
                        else:
                            df['price'] = None
                        for col in standard_cols:
                            if col not in df.columns:
                                df[col] = None
                        df = df[standard_cols]
                        dfs.append(df)
                    except Exception as e:
                        pass
    if dfs:
        buybox_df = pd.concat(dfs, ignore_index=True)
        buybox_df['date'] = pd.to_datetime(buybox_df['date'], errors='coerce')
        buybox_df['asin'] = buybox_df['asin'].astype(str).str.upper().str.strip()
    else:
        buybox_df = pd.DataFrame(columns=standard_cols)
    rows = []
    for (asin, dt), grp in buybox_df.groupby(['asin', 'date']):
        row = {'ASIN': asin, 'Date': dt, 'time': grp['time'].iloc[0], 'product_name': grp['product_name'].iloc[0], 'link': grp['link'].iloc[0], 'rating': grp['rating'].iloc[0] if 'rating' in grp.columns else '', 'reviews': grp['reviews'].iloc[0] if 'reviews' in grp.columns else '', 'bsr_main': grp['bsr_main'].iloc[0] if 'bsr_main' in grp.columns else '', 'bsr_sub': grp['bsr_sub'].iloc[0] if 'bsr_sub' in grp.columns else ''}
        owner = grp[grp['buybox'] == 'YES']
        if not owner.empty:
            row['current_owner'] = owner.iloc[0]['sold_by']
            row['current_owner_price'] = owner.iloc[0]['price']
            row['current_owner_moq'] = owner.iloc[0]['moq']
        hijackers = grp[grp['buybox'] != 'YES']
        for i, (_, r) in enumerate(hijackers.iterrows(), start=1):
            row[f'hijacker_{i}'] = r['sold_by']
            row[f'hijacker_{i}_price'] = r['price']
            row[f'hijacker_{i}_moq'] = r['moq']
        rows.append(row)
    buybox_transposed = pd.DataFrame(rows)
    if not buybox_transposed.empty:
        buybox_transposed['Date'] = pd.to_datetime(buybox_transposed['Date'], errors='coerce').dt.normalize()
        buybox_transposed['ASIN'] = buybox_transposed['ASIN'].astype(str).str.upper().str.strip()
        buybox_transposed = buybox_transposed.drop_duplicates(subset=['ASIN', 'Date'])
    vc_inv_base = align_cols(amz_inv_final, INVENTORY_COLS).copy()
    vc_inv_base['Date'] = pd.to_datetime(vc_inv_base['Date'], errors='coerce').dt.normalize()
    vc_inv_base['ASIN'] = vc_inv_base['ASIN'].astype(str).str.upper().str.strip()
    buybox_merged = vc_inv_base.merge(buybox_transposed, on=['ASIN', 'Date'], how='left')
    hijacker_name_cols = [c for c in buybox_merged.columns if c.startswith('hijacker_') and '_price' not in c and ('_moq' not in c)]
    hijacker_price_cols = [c for c in buybox_merged.columns if 'hijacker_' in c and '_price' in c]
    buybox_merged['hijacker_count'] = buybox_merged[hijacker_name_cols].notna().sum(axis=1)
    buybox_merged['min_hijacker_price'] = buybox_merged[hijacker_price_cols].min(axis=1) if hijacker_price_cols else np.nan
    buybox_merged['price_gap'] = buybox_merged['current_owner_price'] - buybox_merged['min_hijacker_price']
    buybox_merged['is_hijacked'] = buybox_merged['hijacker_count'].apply(lambda x: 'YES' if x > 0 else 'NO')
    buybox_merged = buybox_merged.fillna(0)
    buybox_output = buybox_merged.copy()
    rename_columns = {'ASIN': 'asin', 'Available Inventory': 'available_inventory', 'Sellable Inventory Amount': 'sellable_inventory_amount', 'Unsellable On Hand Inventory Amount': 'unsellable_on_hand_inventory_amount', 'Unsellable On Hand Units': 'unsellable_on_hand_units', 'Vendor Confirmation %': 'vendor_confirmation_pct', 'PO_received_amount': 'po_received_amount', 'PO_received_Units': 'po_received_units', 'Open Pos': 'open_pos', 'Open POs': 'open_pos', 'Receive_Fill_Rate': 'receive_fill_rate', 'Overall Vendor Lead Time (days)': 'overall_vendor_lead_time_days', 'Aged 90+ Days Sellable Inventory': 'aged_90_days_sellable_inventory', 'Aged 90+ Days Sellable Units': 'aged_90_days_sellable_units', 'Date': 'date', 'Sales Channel': 'sales_channel', 'Instock Rate': 'instock_rate', 'Last 30 Days Sales': 'units_shipped_t30', 'DOS': 'dos', 'OOS Date': 'oos_date', 'Stock_Status': 'stock_status', 'No/Low Stock wt Open Pos': 'no_low_stock_wt_open_pos', 'No/Low Stock wt Open POs': 'no_low_stock_wt_open_pos', 'No/Low Stock wt no Open Pos': 'no_low_stock_wt_no_open_pos', 'No/Low Stock wt no Open POs': 'no_low_stock_wt_no_open_pos', 'Brand': 'brand', 'Product Category': 'product_category', 'Product Sub Category': 'product_sub_category', 'Product Name': 'product_name', 'Pack Type': 'pack_type', 'Pack Size': 'pack_size', 'SC Ideal Price': 'sc_ideal_price', 'VC Ideal Price': 'vc_ideal_price', 'time': 'date_temp', 'link': 'current_owner', 'rating': 'current_owner_price', 'reviews': 'current_owner_moq', 'bsr_main': 'min_hijacker_price', 'bsr_sub': 'price_gap'}
    buybox_output.rename(columns=rename_columns, inplace=True)
    required_columns = ['asin', 'brand', 'product_sub_category', 'vendor_confirmation_pct', 'po_received_amount', 'po_received_units', 'open_pos', 'receive_fill_rate', 'overall_vendor_lead_time_days', 'aged_90_days_sellable_inventory', 'aged_90_days_sellable_units', 'sellable_inventory_amount', 'available_inventory', 'unsellable_on_hand_inventory_amount', 'unsellable_on_hand_units', 'date', 'product_name', 'product_category', 'pack_type', 'pack_size', 'sc_ideal_price', 'vc_ideal_price', 'sales_channel', 'in_stock_flag', 'cumulative_instock_days', 'day_of_month', 'instock_rate', 'total_sales', 'total_units', 'sell_through', 'dos', 'oos_date', 'min_available_qty', 'max_available_qty', 'stock_status', 'no_low_stock_wt_open_pos', 'no_low_stock_wt_no_open_pos', 'date_temp', 'current_owner', 'current_owner_price', 'current_owner_moq', 'hijacker_1', 'hijacker_1_price', 'hijacker_1_moq', 'hijacker_2', 'hijacker_2_price', 'hijacker_2_moq', 'hijacker_3', 'hijacker_3_price', 'hijacker_3_moq', 'hijacker_4', 'hijacker_4_price', 'hijacker_4_moq', 'hijacker_5', 'hijacker_5_price', 'hijacker_5_moq', 'hijacker_6', 'hijacker_6_price', 'hijacker_6_moq', 'hijacker_7', 'hijacker_7_price', 'hijacker_7_moq', 'hijacker_8', 'hijacker_8_price', 'hijacker_8_moq', 'hijacker_9', 'hijacker_9_price', 'hijacker_9_moq', 'hijacker_10', 'hijacker_10_price', 'hijacker_10_moq', 'hijacker_11', 'hijacker_11_price', 'hijacker_11_moq', 'hijacker_12', 'hijacker_12_price', 'hijacker_12_moq', 'hijacker_13', 'hijacker_13_price', 'hijacker_13_moq', 'hijacker_14', 'hijacker_14_price', 'hijacker_14_moq', 'hijacker_15', 'hijacker_15_price', 'hijacker_15_moq', 'hijacker_16', 'hijacker_16_price', 'hijacker_16_moq', 'hijacker_17', 'hijacker_17_price', 'hijacker_17_moq', 'hijacker_18', 'hijacker_18_price', 'hijacker_18_moq', 'hijacker_19', 'hijacker_19_price', 'hijacker_19_moq', 'hijacker_20', 'hijacker_20_price', 'hijacker_20_moq', 'sku', 'fnsku', 'condition', 'your_price', 'mfn_listing_exists', 'mfn_fulfillable_quantity', 'afn_listing_exists', 'afn_warehouse_quantity', 'afn_fulfillable_quantity', 'afn_unsellable_quantity', 'afn_reserved_quantity', 'afn_total_quantity', 'per_unit_volume', 'afn_inbound_working_quantity', 'afn_inbound_shipped_quantity', 'afn_inbound_receiving_quantity', 'afn_researching_quantity', 'afn_reserved_future_supply', 'afn_future_supply_buyable', 'store', 'reserved_qty', 'reserved_customerorders', 'reserved_fc_transfers', 'reserved_fc_processing', 'units_shipped_t30', 'units_shipped_t60', 'units_shipped_t90']
    text_columns = [c for c in required_columns if any((x in c for x in ['asin', 'brand', 'product', 'pack', 'sales_channel', 'stock_status', 'condition', 'store', 'sku', 'fnsku', 'date_temp', 'current_owner', 'oos_date', 'hijacker']))]
    missing_columns = []
    for col in required_columns:
        if col not in buybox_output.columns:
            missing_columns.append(col)
            if col in text_columns:
                buybox_output[col] = ''
            else:
                buybox_output[col] = 0
    extra_columns = [c for c in buybox_output.columns if c not in required_columns]
    buybox_output = buybox_output[required_columns + extra_columns]
    DATE_FMT = '%d-%b-%Y'

    def finalize_export(df, rename_map, final_cols, date_cols=()):
        """Select -> rename -> add country/client_id -> format dates -> reorder."""
        out = df.copy()
        out.columns = out.columns.astype(str).str.strip()
        out = out.rename(columns=rename_map)
        for col in final_cols:
            if col not in out.columns:
                out[col] = np.nan
        out['country'] = COUNTRY
        out['client_id'] = CLIENT_ID
        for col in date_cols:
            if col in out.columns:
                out[col] = pd.to_datetime(out[col], errors='coerce').dt.strftime(DATE_FMT)
        return out[final_cols]
    AMZ_INV_RENAME = {'ASIN': 'asin', 'Brand': 'brand', 'Product Sub Category': 'product_sub_category', 'Vendor Confirmation %': 'vendor_confirmation_pct', 'PO_received_amount': 'po_received_amount', 'PO_received_Units': 'po_received_units', 'Open POs': 'open_pos', 'Receive_Fill_Rate': 'receive_fill_rate', 'Overall Vendor Lead Time (days)': 'overall_vendor_lead_time_days', 'Aged 90+ Days Sellable Inventory': 'aged_90_plus_days_sellable_inventory', 'Aged 90+ Days Sellable Units': 'aged_90_plus_days_sellable_units', 'Sellable Inventory Amount': 'sellable_inventory_amount', 'Available Inventory': 'available_inventory', 'Unsellable On Hand Inventory Amount': 'unsellable_on_hand_inventory_amount', 'Unsellable On Hand Units': 'unsellable_on_hand_units', 'Date': 'date', 'Product Name': 'product_name', 'Product Category': 'product_category', 'Pack Type': 'pack_type', 'Pack Size': 'pack_size', 'SC Ideal Price': 'sc_ideal_price', 'VC Ideal Price': 'vc_ideal_price', 'Sales Channel': 'sales_channel', 'cumulative_instock_days': 'cumulative_instock_days', 'day_of_month': 'day_of_month', 'Instock Rate': 'instock_rate'}
    AMZ_INV_COLS = ['asin', 'brand', 'product_sub_category', 'vendor_confirmation_pct', 'po_received_amount', 'po_received_units', 'open_pos', 'receive_fill_rate', 'overall_vendor_lead_time_days', 'aged_90_plus_days_sellable_inventory', 'aged_90_plus_days_sellable_units', 'sellable_inventory_amount', 'available_inventory', 'unsellable_on_hand_inventory_amount', 'unsellable_on_hand_units', 'date', 'product_name', 'product_category', 'pack_type', 'pack_size', 'sc_ideal_price', 'vc_ideal_price', 'sales_channel', 'in_stock_flag', 'cumulative_instock_days', 'day_of_month', 'instock_rate', 'country', 'client_id']
    if 'Sales Channel' not in amz_ads_campaign.columns:
        amz_ads_campaign = amz_ads_campaign.merge(helper_df[['ASIN', 'Sales Channel']], on='ASIN', how='left')
    if 'VC Ideal Price' not in amz_ads_campaign.columns:
        amz_ads_campaign = amz_ads_campaign.merge(helper_df[['ASIN', 'VC Ideal Price']], on='ASIN', how='left')
    amz_inventory_export = finalize_export(amz_inv_final[amz_inv_final['Sales Channel'] == 'Vendor Central'], AMZ_INV_RENAME, AMZ_INV_COLS, date_cols=['date'])
    ORDERS_COL_CANDIDATES = ['14 Day Total Orders (#)', '7 Day Total Orders (#)', 'Total Orders (#)']
    for cand in ORDERS_COL_CANDIDATES:
        if cand in amz_ads_df.columns:
            amz_ads_campaign['orders'] = amz_ads_df.loc[amz_ads_campaign.index, cand] if cand in amz_ads_df.columns else np.nan
            break
    else:
        amz_ads_campaign['orders'] = np.nan
    AMZ_ADS_RENAME = {'ASIN': 'asin', 'Date': 'date', 'Impressions': 'impressions', 'Clicks': 'clicks', 'ads_spend': 'ads_spend', 'ads_sales': 'ads_sale', 'ads_unit_sold': 'units', 'CVR': 'conversion_rate', 'Cost Per Click (CPC)': 'cpc', 'Total Return on Advertising Spend (ROAS)': 'roas', 'Total Advertising Cost of Sales (ACOS)': 'acos', 'Campaign Name': 'campaign_name', 'Portfolio name': 'portfolio_name', 'Campaign Type': 'report_type', 'Product Name': 'product_name', 'Product Category': 'product_category', 'Pack Type': 'pack_type', 'Pack Size': 'pack_size', 'SC Ideal Price': 'sc_ideal_price', 'VC Ideal Price': 'vc_ideal_price'}
    AMZ_ADS_COLS = ['asin', 'date', 'impressions', 'clicks', 'ads_spend', 'ads_sale', 'orders', 'units', 'conversion_rate', 'cpc', 'roas', 'acos', 'campaign_name', 'portfolio_name', 'report_type', 'product_name', 'product_category', 'pack_type', 'pack_size', 'sc_ideal_price', 'vc_ideal_price', 'sales_channel', 'country', 'client_id']
    amz_ads_export = finalize_export(amz_ads_campaign[amz_ads_campaign['Sales Channel'] == 'Vendor Central'], AMZ_ADS_RENAME, AMZ_ADS_COLS, date_cols=['date'])
    AMZ_ORDERS_RENAME = {'ASIN': 'asin', 'Product Name': 'product_name', 'Brand': 'brand', 'Product Category': 'product_category', 'Product Sub Category': 'product_sub_category', 'total_sales': 'total_sales', 'total_units': 'total_units', 'Date': 'date'}
    AMZ_ORDERS_COLS = ['asin', 'product_name', 'brand_code', 'brand', 'product_category', 'product_sub_category', 'parent_asin', 'total_sales', 'shipped_cogs', 'total_units', 'customer_returns', 'confirmed_units', 'sales_discount', 'date', 'country', 'client_id']
    amz_orders_export = finalize_export(amz_rev_df, AMZ_ORDERS_RENAME, AMZ_ORDERS_COLS, date_cols=['date'])
    amz_orders_export = finalize_export(amz_rev_df[amz_rev_df['Sales Channel'] == 'Vendor Central'], AMZ_ORDERS_RENAME, AMZ_ORDERS_COLS, date_cols=['date'])
    AMZ_BUYBOX_COLS = ['asin', 'date', 'current_owner', 'current_owner_price', 'current_owner_moq'] + [f'hijacker_{i}{suf}' for i in range(1, 21) for suf in ('', '_price', '_moq')] + ['product_name', 'category', 'pack_type', 'pack_size', 'sc_ideal_price', 'vc_ideal_price', 'brand', 'sales_channel', 'client_id', 'country']
    amz_buybox_export = finalize_export(buybox_output, {}, AMZ_BUYBOX_COLS, date_cols=['date'])
    NOON_ADS_RENAME = {'ASIN': 'asin', 'Date': 'date', 'Sales Channel': 'sales_channel', 'Campaign Name': 'campaign_name', 'Campaign Type': 'campaign_type', 'ads_sales': 'ads_sales', 'ads_unit_sold': 'ads_unit_sold', 'ads_spend': 'ads_spend', 'Impressions': 'impressions', 'Clicks': 'clicks', 'Click-Thru Rate (CTR)': 'ctr', 'Cost Per Click (CPC)': 'cpc', 'Total Advertising Cost of Sales (ACOS)': 'acos', 'Total Return on Advertising Spend (ROAS)': 'roas', 'CVR': 'cvr', 'Brand': 'brand', 'Product Name': 'product_name', 'Product Category': 'product_category', 'Product Sub Category': 'product_sub_category', 'Pack Type': 'pack_type', 'Pack Size': 'pack_size', 'VC Ideal Price': 'vc_ideal_price'}
    NOON_CORE_ADS_COLS = ['asin', 'date', 'sales_channel', 'campaign_name', 'campaign_type', 'ads_sales', 'ads_unit_sold', 'ads_spend', 'impressions', 'clicks', 'ctr', 'cpc', 'acos', 'roas', 'brand', 'product_name', 'product_category', 'product_sub_category', 'pack_type', 'pack_size', 'vc_ideal_price', 'country', 'client_id']
    NMS_ADS_COLS = ['asin', 'date', 'sales_channel', 'campaign_name', 'campaign_type', 'ads_sales', 'ads_unit_sold', 'ads_spend', 'impressions', 'clicks', 'ctr', 'cpc', 'acos', 'roas', 'cvr', 'brand', 'product_category', 'product_sub_category', 'pack_type', 'pack_size', 'vc_ideal_price', 'country', 'client_id']
    noon_ads_export = finalize_export(noon_ads_campaign, NOON_ADS_RENAME, NOON_CORE_ADS_COLS, date_cols=['date'])
    nms_ads_export = finalize_export(nms_ads_campaign, NOON_ADS_RENAME, NMS_ADS_COLS, date_cols=['date'])
    NOON_INV_RENAME = {'ASIN': 'asin', 'Date': 'date', 'Available Inventory': 'available_inventory', 'Last 30 Days Sales': 'last_30_day_sale_qty', 'DOS': 'dos', 'Brand': 'brand', 'Product Category': 'product_category', 'Product Sub Category': 'product_sub_category', 'Product Name': 'product_name', 'Pack Type': 'pack_type', 'Pack Size': 'pack_size', 'VC Ideal Price': 'vc_ideal_price', 'Sales Channel': 'sales_channel'}
    NOON_INV_COLS = ['asin', 'date', 'available_inventory', 'last_30_day_sale_qty', 'dos', 'brand', 'product_category', 'product_sub_category', 'product_name', 'pack_type', 'pack_size', 'vc_ideal_price', 'sales_channel', 'country', 'client_id']

    def _with_barcode(inv_final, raw_inv_df):
        """Merge the static Barcode field from the raw inventory df (deduped by ASIN)."""
        if 'Barcode' not in raw_inv_df.columns:
            out = inv_final.copy()
            out['Barcode'] = np.nan
            return out
        barcode_lookup = raw_inv_df[['ASIN', 'Barcode']].dropna(subset=['ASIN']).drop_duplicates(subset=['ASIN'], keep='first')
        return inv_final.merge(barcode_lookup, on='ASIN', how='left')
    nc_inventory_export = finalize_export(_with_barcode(nc_inv_final, nc_inv_df), NOON_INV_RENAME, NOON_INV_COLS, date_cols=['date'])
    nms_inventory_export = finalize_export(_with_barcode(nms_inv_final, nms_inv_df), NOON_INV_RENAME, NOON_INV_COLS, date_cols=['date'])
    NOON_REV_RENAME = {'Date': 'date', 'ASIN': 'asin', 'total_units': 'total_units', 'total_sales': 'total_sales', 'Product Name': 'product_name', 'Product Category': 'product_category', 'Pack Size': 'pack_size', 'Brand': 'brand', 'Product Sub Category': 'product_sub_category', 'Pack Type': 'pack_type', 'Sales Channel': 'sales_channel', 'VC Ideal Price': 'vc_ideal_price'}
    NOON_REV_COLS = ['date', 'asin', 'total_units', 'total_sales', 'product_name', 'product_category', 'pack_size', 'country', 'client_id', 'brand', 'product_sub_category', 'pack_type', 'sales_channel', 'vc_ideal_price']
    nc_revenue_export = finalize_export(_with_barcode(nc_rev_final, nc_inv_df), NOON_REV_RENAME, NOON_REV_COLS, date_cols=['date'])
    nms_revenue_export = finalize_export(_with_barcode(nms_rev_final, nms_inv_df), NOON_REV_RENAME, NOON_REV_COLS, date_cols=['date'])
    to_old = {'asin': 'ASIN', 'brand': 'Brand', 'product_category': 'Product Category', 'product_sub_category': 'Product Sub Category', 'product_name': 'Product Name', 'pack_type': 'Pack Type', 'pack_size': 'Pack Size', 'sales_channel': 'Sales Channel', 'date': 'Date'}
    to_new = {v: k for k, v in to_old.items()}

    def run_helper(df):
        temp = df.copy()
        temp.rename(columns={k: v for k, v in to_old.items() if k in temp.columns}, inplace=True)
        if 'Sales Channel' not in temp.columns:
            temp['Sales Channel'] = 'Vendor Central'
        temp = apply_helper(temp)
        temp.rename(columns={k: v for k, v in to_new.items() if k in temp.columns}, inplace=True)
        return temp
    inventory_output = run_helper(inventory_output)
    revenue_output = run_helper(revenue_output)
    marketing_output = run_helper(marketing_output)
    buybox_output = run_helper(buybox_output)

    for _df in (
        amz_inventory_export,
        amz_ads_export,
        amz_orders_export,
        amz_buybox_export,
    ):
        if _df is not None and not _df.empty:
            _df["sales_channel"] = "Vendor Central"

    return {
        "inventory": inventory_output,
        "revenue": revenue_output,
        "marketing": marketing_output,
        "buybox": buybox_output,
        "amazon_inventory": amz_inventory_export,
        "amazon_ads": amz_ads_export,
        "amazon_orders": amz_orders_export,
        "amazon_buybox": amz_buybox_export,
        "noon_ads": noon_ads_export,
        "noon_inventory": nc_inventory_export,
        "noon_revenue": nc_revenue_export,
        "noon_minutes_ads": nms_ads_export,
        "noon_minutes_inventory": nms_inventory_export,
        "noon_minutes_revenue": nms_revenue_export,
        # Pricing came from Selenium-only notebook cells and is intentionally absent.
        "noon_minutes_pricing": pd.DataFrame(),
    }


def finalize_frame(df: pd.DataFrame, *, csv_dates: bool = False) -> pd.DataFrame:
    """Normalize export columns, nulls, and date representation."""
    out = df.copy()
    out.columns = (
        out.columns.astype(str).str.strip().str.lower()
        .str.replace(" ", "_", regex=False).str.replace("-", "_", regex=False)
        .str.replace("(", "", regex=False).str.replace(")", "", regex=False)
        .str.replace("%", "pct", regex=False).str.replace("/", "_", regex=False)
        .str.replace(".", "", regex=False)
    )
    out = out.loc[:, ~out.columns.duplicated()]
    if "date" in out.columns:
        dates = pd.to_datetime(out["date"], errors="coerce")
        out["date"] = dates.dt.strftime("%Y-%m-%d") if csv_dates else dates
    numeric = out.select_dtypes(include=["number"]).columns
    out[numeric] = out[numeric].fillna(0)
    return out.fillna("")


def save_emami_outputs(
    frames: Mapping[str, pd.DataFrame],
    config: EmamiConfig,
) -> list[Path]:
    """
    Save local masters under ``sanity_data/EMM/{report}/``.

    - Excel summaries → ``EMM/emami_report/inventory_output_{year}.xlsx`` …
    - Channel CSV masters → ``EMM/inventory/…``, ``EMM/ads/…``, ``EMM/orders/…``, …
      (same relative layout as Azure blobs under ``sanity_data/``)
    """
    saved: list[Path] = []
    excel_dir = config.excel_folder
    excel_dir.mkdir(parents=True, exist_ok=True)
    workbook_names = {
        "inventory": f"inventory_output_{config.year}.xlsx",
        "revenue": f"revenue_output_{config.year}.xlsx",
        "marketing": f"marketing_output_{config.year}.xlsx",
        "buybox": f"buybox_output_{config.year}.xlsx",
    }
    for key, filename in workbook_names.items():
        frame = frames.get(key)
        if frame is None or frame.empty:
            print(f"[EMM] Skipping empty local output: {key}")
            continue
        path = excel_dir / filename
        finalize_frame(frame).to_excel(path, index=False)
        saved.append(path)
        print(f"[EMM] Saved {key}: {path} ({len(frame):,} rows)")

    for key, blob_path in AZURE_BLOB_KEYS.items():
        frame = frames.get(key)
        if frame is None or frame.empty:
            print(f"[EMM] Skipping empty channel export: {key}")
            continue
        path = config.local_master_path(blob_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        finalize_frame(frame, csv_dates=True).to_csv(
            path, index=False, encoding="utf-8-sig"
        )
        saved.append(path)
        print(f"[EMM] Saved master {key}: {path} ({len(frame):,} rows)")
    return saved


def prompt_yes_no(message: str, *, default: bool = False) -> bool:
    """Ask yes/no. Empty input uses ``default``. Accepts y/yes/n/no."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        try:
            raw = input(message + suffix).strip().lower()
        except EOFError:
            print(
                "\n  No interactive input — defaulting to "
                f"{'YES' if default else 'NO'}."
            )
            return default
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("  Please enter y/yes or n/no.")


def resolve_azure_upload_choice(
    *,
    upload_azure: Optional[bool] = None,
) -> bool:
    """
    Decide whether to sync Emami CSV masters to Azure.

    Priority:
      1) Explicit CLI/run flag (True/False)
      2) Interactive yes/no prompt (default No)
    """
    if upload_azure is True:
        print("[EMM] Azure upload: YES (flag --upload-azure)")
        return True
    if upload_azure is False:
        print("[EMM] Azure upload: NO (flag --skip-azure)")
        return False

    print()
    print("=" * 60)
    print("LOCAL Emami masters have been saved under sanity_data/EMM/{report}/")
    print("Please review them before uploading to Azure.")
    print("=" * 60)
    return prompt_yes_no(
        "Upload Emami CSV masters to Azure?",
        default=False,
    )


def _azure_connection_string() -> str:
    connection = (
        _clean_env("AZURE_STORAGE_CONNECTION_STRING")
        or _clean_env("EMAMI_AZURE_CONNECTION_STRING")
    )
    if not connection:
        raise EnvironmentError(
            "Set AZURE_STORAGE_CONNECTION_STRING or EMAMI_AZURE_CONNECTION_STRING."
        )
    return connection


def _prepare_azure_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Apply cell 168 date normalization and natural-key deduplication."""
    out = finalize_frame(df, csv_dates=True)
    keys = [c for c in ("sales_channel", "date", "asin") if c in out.columns]
    if len(keys) == 3:
        out = out.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)
    return out


def upload_emami_outputs(frames: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Append/dedupe the 11 cell-168 CSV datasets in Azure Blob Storage."""
    from azure.storage.blob import BlobServiceClient, ExponentialRetry
    from report_script.retail.azure_csv_sync import sync_dataframe_to_azure_csv

    container = _clean_env("CONTAINER_NAME_EMAMI") or DEFAULT_CONTAINER
    service = BlobServiceClient.from_connection_string(
        _azure_connection_string(),
        connection_timeout=300,
        read_timeout=600,
        retry_policy=ExponentialRetry(
            initial_backoff=3,
            increment_base=3,
            retry_total=8,
        ),
        max_single_put_size=8 * 1024 * 1024,
        max_block_size=4 * 1024 * 1024,
    )
    uploaded: dict[str, pd.DataFrame] = {}
    for key, blob_path in AZURE_BLOB_KEYS.items():
        frame = frames.get(key)
        if frame is None or frame.empty:
            print(f"[EMM] Azure skip (None/empty): {key}")
            continue
        uploaded[key] = sync_dataframe_to_azure_csv(
            name=key,
            new_df=_prepare_azure_frame(frame),
            blob_path=blob_path,
            blob_service_client=service,
            container_name=container,
        )
    return uploaded


def build_emami_report(
    *,
    year: int | None = None,
    save_output: bool = True,
    upload_azure: Optional[bool] = None,
) -> dict[str, pd.DataFrame]:
    """
    Build Emami UAE frames, save local masters, then optionally upload to Azure.

    ``upload_azure``:
      - True  → upload (CLI ``--upload-azure``)
      - False → skip (CLI ``--skip-azure``)
      - None  → interactive yes/no after local save (default)
    """
    config = get_emami_config(year)
    if not config.helper_file.is_file():
        raise FileNotFoundError(f"Emami helper file not found: {config.helper_file}")
    print(f"[EMM] Year: {config.year}")
    print(f"[EMM] Input root: {config.base}")
    print(f"[EMM] Local root: {config.output_folder}")
    frames = _build_report_frames(config)
    if save_output:
        save_emami_outputs(frames, config)
        do_upload = resolve_azure_upload_choice(upload_azure=upload_azure)
        if do_upload:
            upload_emami_outputs(frames)
        else:
            print("[EMM] Azure upload skipped. Local masters kept.")
            print("[EMM] Re-run with --upload-azure after review if needed.")
    elif upload_azure is True:
        upload_emami_outputs(frames)
    return frames


def run(
    *,
    client: str = "EMM",
    geos: Sequence[str] | str | None = None,
    year: int | None = None,
    save_output: bool = True,
    upload_azure: Optional[bool] = None,
    skip_azure: bool = False,
    **kwargs: Any,
) -> dict[str, pd.DataFrame]:
    """Pipeline entrypoint; Emami supports AE only."""
    del kwargs
    if str(client).strip().upper() != "EMM":
        raise ValueError("emami_report.py only supports client='EMM'.")
    if geos:
        requested = [geos] if isinstance(geos, str) else list(geos)
        invalid = [str(geo).upper() for geo in requested if str(geo).upper() != COUNTRY]
        if invalid:
            raise ValueError(f"Emami report supports AE only; received {invalid}.")
    choice = upload_azure
    if skip_azure:
        choice = False
    elif upload_azure is True:
        choice = True
    return build_emami_report(
        year=year,
        save_output=save_output,
        upload_azure=choice,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Emami UAE multi-channel report")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument(
        "--upload-azure",
        action="store_true",
        help="Upload CSV masters to Azure without prompting",
    )
    parser.add_argument(
        "--skip-azure",
        action="store_true",
        help="Skip Azure upload without prompting",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict[str, pd.DataFrame]:
    args = parse_args(argv)
    choice: Optional[bool] = None
    if args.upload_azure:
        choice = True
    elif args.skip_azure:
        choice = False
    return build_emami_report(
        year=args.year,
        save_output=not args.no_save,
        upload_azure=choice,
    )


if __name__ == "__main__":
    main()
