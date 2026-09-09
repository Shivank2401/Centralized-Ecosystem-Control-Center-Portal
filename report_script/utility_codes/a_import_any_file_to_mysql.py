"""
Import any CSV/Excel file to MySQL (auto-create table, snake_case columns).

Covers:
  - Credentials from .env: MYSQL_HOST/PORT/USER/PASSWORD/DATABASE (+ optional pool)
  - Reads CSV or Excel; creates table if missing; bulk insert with progress bar
  - Not client/geo-specific — interactive or --file / --table CLI

Run:
    python report_script/utility_codes/a_import_any_file_to_mysql.py
    python report_script/utility_codes/a_import_any_file_to_mysql.py --file data.csv --table my_table
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd
from mysql.connector import pooling
from tqdm import tqdm

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import paths as cfg_paths  # noqa: F401  # loads .env

# =============================================================================
# MySQL CONFIGURATION (from env; same keys/behavior as original)
# =============================================================================

DB_NAME = os.getenv("MYSQL_DATABASE", "datahive_esh_test").strip() or "datahive_esh_test"


def _mysql_config() -> dict:
    password = os.getenv("MYSQL_PASSWORD", "").strip()
    if not password:
        raise EnvironmentError(
            "Missing MYSQL_PASSWORD. Set it in .env (see .env.example)."
        )
    port_raw = os.getenv("MYSQL_PORT", "3306").strip() or "3306"
    pool_size_raw = os.getenv("MYSQL_POOL_SIZE", "12").strip() or "12"
    return {
        "pool_name": os.getenv("MYSQL_POOL_NAME", "order_pool").strip() or "order_pool",
        "pool_size": int(pool_size_raw),
        "host": os.getenv("MYSQL_HOST", "192.168.50.148").strip() or "192.168.50.148",
        "port": int(port_raw),
        "user": os.getenv("MYSQL_USER", "datahive_esh_test").strip() or "datahive_esh_test",
        "password": password,
        "database": DB_NAME,
        "autocommit": True,
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _print_header(title: str):
    """Print a formatted header."""
    bar = "=" * 60
    print(f"\n{bar}\n{title}\n{bar}")


def to_snake_case(name: str) -> str:
    """
    Convert column name to snake_case.

    Examples:
        "Invoice Value" -> "invoice_value"
        "GST-IN" -> "gst_in"
        "Date/Time" -> "date_time"
    """
    # Replace spaces and special characters with underscores
    name = re.sub(r"[^\w\s-]", "", str(name))
    # Replace spaces and hyphens with underscores
    name = re.sub(r"[\s-]+", "_", name)
    # Convert to lowercase
    name = name.lower()
    # Remove leading/trailing underscores
    name = name.strip("_")
    # Replace multiple underscores with single underscore
    name = re.sub(r"_+", "_", name)
    return name


def read_file(file_path: Path) -> pd.DataFrame:
    """
    Read CSV or Excel file and return DataFrame.

    Args:
        file_path: Path to the file

    Returns:
        DataFrame with the file data
    """
    ext = file_path.suffix.lower()

    try:
        if ext in [".xlsx", ".xls"]:
            df = pd.read_excel(file_path)
        elif ext == ".csv":
            df = pd.read_csv(file_path)
        else:
            raise ValueError(
                f"Unsupported file format: {ext}. Supported formats: .csv, .xlsx, .xls"
            )

        print("File loaded successfully")
        print(f"   Rows: {len(df)}")
        print(f"   Columns: {len(df.columns)}")
        return df

    except Exception as e:
        raise ValueError(f"Error reading file: {e}")


def get_mysql_type(dtype: str) -> str:
    """
    Convert pandas dtype to MySQL data type.

    Args:
        dtype: Pandas dtype string

    Returns:
        MySQL data type string
    """
    dtype_str = str(dtype).lower()

    if "int" in dtype_str:
        # Use BIGINT to avoid out-of-range errors for large IDs
        return "BIGINT"
    elif "float" in dtype_str or "double" in dtype_str:
        return "DOUBLE"
    elif "datetime" in dtype_str or "date" in dtype_str:
        return "DATETIME"
    elif "bool" in dtype_str:
        return "BOOLEAN"
    else:
        return "TEXT"


def escape_mysql_identifier(identifier: str) -> str:
    """
    Escape MySQL identifier (table/column name) by replacing backticks.

    Args:
        identifier: Identifier name

    Returns:
        Escaped identifier
    """
    return identifier.replace("`", "``")


def import_to_mysql(df: pd.DataFrame, table_name: str, drop_existing: bool = True) -> None:
    """
    Import DataFrame to MySQL database.

    Args:
        df: DataFrame to import
        table_name: Name of the table to create/update
        drop_existing: If True, drop existing table before creating new one
    """
    mysql_cfg = _mysql_config()

    # Convert column names to snake_case
    df_snake = df.copy()
    df_snake.columns = [to_snake_case(col) for col in df.columns]

    print("\nColumn name conversion:")
    for old, new in zip(df.columns[:10], df_snake.columns[:10]):  # Show first 10
        if old != new:
            print(f"   '{old}' -> '{new}'")
    if len(df.columns) > 10:
        print(f"   ... and {len(df.columns) - 10} more columns")

    # Create connection pool
    pool_config = {
        "pool_name": mysql_cfg["pool_name"],
        "pool_size": mysql_cfg["pool_size"],
        "pool_reset_session": True,
        "host": mysql_cfg["host"],
        "port": mysql_cfg["port"],
        "user": mysql_cfg["user"],
        "password": mysql_cfg["password"],
        "database": mysql_cfg["database"],
        "autocommit": mysql_cfg["autocommit"],
    }

    cnxpool = pooling.MySQLConnectionPool(**pool_config)
    cnx = cnxpool.get_connection()
    cursor = cnx.cursor()

    try:
        # Drop table if exists
        if drop_existing:
            print(f"\nDropping existing table '{table_name}' if it exists...")
            cursor.execute(f"DROP TABLE IF EXISTS `{escape_mysql_identifier(table_name)}`")

        # Create table based on DataFrame structure
        print(f"\nCreating table '{table_name}'...")
        create_table_query = f"CREATE TABLE `{escape_mysql_identifier(table_name)}` ("
        column_defs = []

        for col in df_snake.columns:
            mysql_type = get_mysql_type(str(df_snake[col].dtype))
            col_name_escaped = escape_mysql_identifier(col)
            column_defs.append(f"`{col_name_escaped}` {mysql_type}")

        create_table_query += ", ".join(column_defs) + ")"
        cursor.execute(create_table_query)
        print("Table created successfully")

        # Prepare insert statement
        col_names_escaped = [f"`{escape_mysql_identifier(col)}`" for col in df_snake.columns]
        placeholders = ", ".join(["%s"] * len(df_snake.columns))
        insert_query = (
            f"INSERT INTO `{escape_mysql_identifier(table_name)}` "
            f"({', '.join(col_names_escaped)}) VALUES ({placeholders})"
        )

        # Convert DataFrame to list of tuples, handling NaN values
        print("\nPreparing data for insertion...")
        data_to_insert = []
        for _, row in df_snake.iterrows():
            row_values = []
            for val in row:
                if pd.isna(val):
                    row_values.append(None)
                else:
                    row_values.append(val)
            data_to_insert.append(tuple(row_values))

        # Insert data in batches
        print(f"\nInserting {len(data_to_insert)} rows...")
        batch_size = 1000
        for i in tqdm(range(0, len(data_to_insert), batch_size), desc="Inserting data"):
            batch = data_to_insert[i : i + batch_size]
            cursor.executemany(insert_query, batch)
            cnx.commit()

        print("\nData imported successfully!")
        print(f"   Database: {mysql_cfg['database']}")
        print(f"   Table: {table_name}")
        print(f"   Rows inserted: {len(data_to_insert)}")

    except Exception as e:
        cnx.rollback()
        print(f"\nError importing to MySQL: {e}")
        print(traceback.format_exc())
        raise
    finally:
        cursor.close()
        cnx.close()


def process_import(
    *,
    file_path: Optional[Path] = None,
    table_name: Optional[str] = None,
    drop_existing: Optional[bool] = None,
    interactive: bool = True,
) -> None:
    """Core import flow. Prompts for missing values when interactive=True."""
    _print_header("IMPORT FILE TO MYSQL/phpMyAdmin")

    if file_path is None and interactive:
        print("\nEnter the input file path (CSV or Excel, drag-drop allowed):")
        file_input = input("> ").strip().strip('"').strip("'")
        if not file_input:
            raise SystemExit("No file path provided.")
        file_path = Path(file_input).expanduser().resolve()
    if file_path is None:
        raise SystemExit("No file path provided. Pass --file or run interactively.")

    file_path = Path(file_path).expanduser().resolve()
    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    _print_header("READING FILE")
    df = read_file(file_path)

    if not table_name and interactive:
        print("\n" + "=" * 60)
        print("TABLE NAME")
        print("=" * 60)
        print("Enter the table name (will be created in MySQL):")
        table_name = input("> ").strip()
    if not table_name:
        raise SystemExit("No table name provided. Pass --table or run interactively.")

    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
        raise SystemExit(
            "Invalid table name. Use only letters, numbers, and underscores."
        )

    if drop_existing is None:
        if interactive:
            print("\nDrop existing table if it exists? (y/n, default: y):")
            drop_existing_input = input("> ").strip().lower()
            drop_existing = drop_existing_input != "n"
        else:
            drop_existing = True

    _print_header("IMPORTING TO MYSQL")
    import_to_mysql(df, table_name, drop_existing=bool(drop_existing))


def run(*, client: str = "ESH", geos=None, **_kwargs) -> None:
    """Pipeline entry — interactive prompts (client/geos unused)."""
    _ = (client, geos)
    process_import(interactive=True)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import CSV/Excel to MySQL")
    p.add_argument("--file", default="", help="CSV or Excel path")
    p.add_argument("--table", default="", help="MySQL table name")
    p.add_argument(
        "--drop-existing",
        dest="drop_existing",
        action="store_true",
        default=None,
        help="Drop table if it exists (default when non-interactive)",
    )
    p.add_argument(
        "--keep-existing",
        dest="drop_existing",
        action="store_false",
        help="Do not drop existing table",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    file_path = Path(args.file).expanduser().resolve() if str(args.file).strip() else None
    table_name = str(args.table).strip() or None
    interactive = file_path is None or table_name is None or args.drop_existing is None
    try:
        process_import(
            file_path=file_path,
            table_name=table_name,
            drop_existing=args.drop_existing,
            interactive=interactive,
        )
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(1)
    except EnvironmentError as e:
        print(f"\nError: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        print(traceback.format_exc())
        sys.exit(1)


from config_manager.report_helpers import print_script_completed

if __name__ == "__main__":
    main()
    print_script_completed('a_import_any_file_to_mysql')
