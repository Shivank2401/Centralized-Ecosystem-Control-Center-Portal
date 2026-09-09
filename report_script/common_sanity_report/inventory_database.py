"""
Client-aware Amazon inventory database (manage_fba + reserved + ageing).

Covers:
  - Clients: ESH + KNC (geos from client.yaml)
  - Inputs (must exist): manage_fba, reserved, ageing parquet under sanity_data/{CLIENT}/
  - Ageing date +1 for US/CA; FC transfer AE/IN from ageing else manage/reserved rules
  - Outputs: sanity_data/{CLIENT}/inventory_database/{GEO}_inventory_database.parquet|.csv

Does not re-read raw Amazon downloads — only merges sanity slices.

Adding a NEW client (no ETL changes needed):
  1. Add client + geos in client.yaml / geography.yaml / layouts.py
  2. Optionally add an entry in CLIENT_OVERRIDES (sku_backend / geo rule sets)
  3. List the client on this report in report.yaml
  Client identity + geo list come from YAML automatically.

Style: step-by-step prints (>>> STEP). ETL formulas unchanged.

Run:
    python report_script/common_sanity_report/inventory_database.py
    python report_script/common_sanity_report/inventory_database.py --client ESH
    python report_script/common_sanity_report/inventory_database.py --client KNC --geos UK,DE,AE
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import layouts, paths as cfg_paths
from config_manager.loader import load_geographies
from config_manager.report_helpers import print_script_completed
from report_script.common_sanity_report.new_sku_check import (
    check_final_dataframe_new_skus,
)
from report_script.common_sanity_report.run_logs import (
    ReportRunLog,
    format_inventory_database_geo_section,
)


# =============================================================================
# Run knobs + merge constants (ETL)
# =============================================================================

CLIENT: str = "ESH" | "KNC" # "ESH" | "KNC"
PROCESS_GEOS: Optional[List[str]] = None
SAVE_OUTPUT = True

PARQUET_NAME_SUFFIX = "inventory_database"
OUTPUT_SUBDIR = "inventory_database"

# Default geo rules (apply to any client unless overridden)
DEFAULT_AGEING_DATE_PLUS_ONE_GEOS = {"US", "CA"}
DEFAULT_FC_TRANSFER_FROM_AGEING_GEOS = {"AE", "IN"}

AGEING_KEEP_COLS = ["geography", "date", "sku", "fc_transfer"]
RESERVED_DROP_COLS = ["client", "client_id"]
MERGE_KEYS_MANAGE_RESERVED = ["geography", "platform", "date", "sku"]
MERGE_KEYS_AGEING = ["geography", "date", "sku"]
CALC_COLS = [
    "fc_transfer",
    "reserved_fc_transfers",
    "afn_fc_transfer_quantity",
    "afn_reserved_quantity",
    "reserved_qty",
]


# =============================================================================
# Client configuration
#   Identity + geos come from YAML. CLIENT_OVERRIDES only for sku_backend / rules.
# =============================================================================

@dataclass(frozen=True)
class ClientInventoryOverrides:
    sku_backend: str = "esh"
    ageing_date_plus_one_geos: Set[str] = field(
        default_factory=lambda: set(DEFAULT_AGEING_DATE_PLUS_ONE_GEOS)
    )
    fc_transfer_from_ageing_geos: Set[str] = field(
        default_factory=lambda: set(DEFAULT_FC_TRANSFER_FROM_AGEING_GEOS)
    )


# Register known clients here. Unknown clients still work via YAML + defaults.
CLIENT_OVERRIDES: Dict[str, ClientInventoryOverrides] = {
    "ESH": ClientInventoryOverrides(sku_backend="esh"),
    "KNC": ClientInventoryOverrides(sku_backend="knc"),
}


@dataclass(frozen=True)
class InventoryDbConfig:
    client_code: str
    client_id: str
    client_name: str
    geos: List[str]
    sku_backend: str
    sanity_root: Path
    output_dir: Path
    ageing_date_plus_one_geos: Set[str] = field(
        default_factory=lambda: set(DEFAULT_AGEING_DATE_PLUS_ONE_GEOS)
    )
    fc_transfer_from_ageing_geos: Set[str] = field(
        default_factory=lambda: set(DEFAULT_FC_TRANSFER_FROM_AGEING_GEOS)
    )


def _client_geos(client: str) -> List[str]:
    return [str(g).upper() for g in load_geographies(client)]


def _overrides_for(client_code: str) -> ClientInventoryOverrides:
    return CLIENT_OVERRIDES.get(
        client_code.upper(),
        ClientInventoryOverrides(),
    )


def get_inventory_db_config(
    client: str,
    geos: Optional[Sequence[str]] = None,
) -> InventoryDbConfig:
    ident = layouts.client_identity(client)
    code = ident["client_code"]
    allowed = _client_geos(code)
    overrides = _overrides_for(code)

    if geos:
        wanted = [str(g).strip().upper() for g in geos if str(g).strip()]
        selected = [g for g in wanted if g in allowed]
        skipped = [g for g in wanted if g not in allowed]
        if skipped:
            print(f"[WARN] [{code}] geos not in client.yaml, skipped: {skipped}")
        if not selected:
            selected = allowed
    else:
        selected = allowed

    sanity = cfg_paths.sanity_data_root() / code
    return InventoryDbConfig(
        client_code=code,
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        geos=selected,
        sku_backend=overrides.sku_backend,
        sanity_root=sanity,
        output_dir=sanity / OUTPUT_SUBDIR,
        ageing_date_plus_one_geos=set(overrides.ageing_date_plus_one_geos),
        fc_transfer_from_ageing_geos=set(overrides.fc_transfer_from_ageing_geos),
    )


def output_dir_for(client_code: str) -> Path:
    return cfg_paths.sanity_data_root() / str(client_code).upper() / OUTPUT_SUBDIR


def known_clients() -> List[str]:
    """CLI choices: registered overrides (extend when adding CLIENT_OVERRIDES)."""
    return sorted(CLIENT_OVERRIDES.keys())


# =============================================================================
# Load sanity parquet slices
# =============================================================================

def _geo_parquet(root: Path, folder: str, geo: str, suffix: str) -> Path:
    return root / folder / f"{geo.upper()}_{suffix}.parquet"


def load_parquet_or_empty(
    path: Path,
    *,
    client: str,
    geo: str,
    label: str,
    columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    if not path.is_file():
        print(f"[{client}] [{geo}] {label} MISSING -> {path}")
        return pd.DataFrame()
    df = pd.read_parquet(path, columns=list(columns) if columns else None)
    print(f"[{client}] [{geo}] {label} loaded {len(df):,} rows <- {path.name}")
    return df


def _ensure_calc_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in CALC_COLS:
        if col not in out.columns:
            out[col] = 0
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


# =============================================================================
# Transform (ETL — do not change formulas when cleaning style)
# =============================================================================

def build_geography_inventory(
    cfg: InventoryDbConfig,
    geo: str,
) -> pd.DataFrame:
    """Notebook merge + FC-transfer / reserved-qty rules for one geography."""
    client = cfg.client_code
    print(f"\n>>> STEP: [{client}] {geo} — load manage_fba + reserved + ageing")

    manage_fba = load_parquet_or_empty(
        _geo_parquet(cfg.sanity_root, "manage_fba", geo, "manage_fba_inventory"),
        client=client,
        geo=geo,
        label="manage_fba",
    )
    reserved = load_parquet_or_empty(
        _geo_parquet(cfg.sanity_root, "reserved", geo, "reserved_inventory"),
        client=client,
        geo=geo,
        label="reserved",
    )
    ageing = load_parquet_or_empty(
        _geo_parquet(cfg.sanity_root, "ageing", geo, "ageing_inventory"),
        client=client,
        geo=geo,
        label="ageing",
    )

    if manage_fba.empty:
        print(f"[{client}] [{geo}] skip — manage_fba is required and empty")
        return pd.DataFrame()

    print(f">>> STEP: [{client}] {geo} — merge + FC / reserved rules")
    manage_fba = manage_fba.copy()
    manage_fba["date"] = pd.to_datetime(manage_fba["date"], errors="coerce")

    if not reserved.empty:
        reserved = reserved.copy()
        reserved["date"] = pd.to_datetime(reserved["date"], errors="coerce")
        reserved = reserved.drop(
            columns=[c for c in RESERVED_DROP_COLS if c in reserved.columns]
        )

    if not ageing.empty:
        keep = [c for c in AGEING_KEEP_COLS if c in ageing.columns]
        ageing = ageing.loc[:, keep].copy()
        ageing["date"] = pd.to_datetime(ageing["date"], errors="coerce")
        # Convert date to datetime and add 1 day if geography is US and CA else add 0 days
        if geo.upper() in cfg.ageing_date_plus_one_geos:
            ageing["date"] = ageing["date"] + pd.Timedelta(days=1)

    inventory_database = manage_fba
    if not reserved.empty:
        inventory_database = pd.merge(
            inventory_database,
            reserved,
            on=[
                c
                for c in MERGE_KEYS_MANAGE_RESERVED
                if c in inventory_database.columns and c in reserved.columns
            ],
            how="left",
        )
    if not ageing.empty:
        inventory_database = pd.merge(
            inventory_database,
            ageing,
            on=[
                c
                for c in MERGE_KEYS_AGEING
                if c in inventory_database.columns and c in ageing.columns
            ],
            how="left",
        )
    inventory_database = _ensure_calc_columns(inventory_database)
    inventory_database = inventory_database.fillna(0)

    # geography based fc transfer quantity calculation:
    inventory_database["new_afn_fc_transfer_quantity"] = np.where(
        inventory_database["geography"].isin(list(cfg.fc_transfer_from_ageing_geos)),
        # For AE and IN
        np.where(
            inventory_database["fc_transfer"] == 0,
            inventory_database["reserved_fc_transfers"],
            inventory_database["fc_transfer"],
        ),
        # For all other geographies
        np.where(
            inventory_database["afn_fc_transfer_quantity"] == 0,
            inventory_database["reserved_fc_transfers"],
            inventory_database["afn_fc_transfer_quantity"],
        ),
    )

    inventory_database["afn_reserved_quantity"] = np.where(
        inventory_database["afn_reserved_quantity"] == 0,
        inventory_database["reserved_qty"],
        inventory_database["afn_reserved_quantity"],
    )

    inventory_database = inventory_database.drop(
        columns=[
            c
            for c in (
                "afn_fc_transfer_quantity",
                "reserved_fc_transfers",
                "fc_transfer",
                "reserved_qty",
            )
            if c in inventory_database.columns
        ]
    )
    inventory_database = inventory_database.rename(
        columns={"new_afn_fc_transfer_quantity": "afn_fc_transfer_quantity"}
    )

    inventory_database["client"] = client
    inventory_database["client_id"] = cfg.client_id
    inventory_database["geography"] = geo.upper()
    if "platform" not in inventory_database.columns:
        inventory_database["platform"] = "amazon"

    print(
        f"[{client}] [{geo}] inventory_database rows={len(inventory_database):,} "
        f"cols={len(inventory_database.columns)}"
    )
    return inventory_database


def save_geography_outputs(
    df: pd.DataFrame,
    output_dir: Path,
    name_suffix: str = PARQUET_NAME_SUFFIX,
) -> List[Path]:
    if df.empty:
        print("[WARN] Nothing to save — DataFrame is empty")
        return []
    if "geography" not in df.columns:
        raise KeyError("Expected 'geography' column")

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    print(f"\n>>> STEP: save per-geography inventory_database → {output_dir}")
    for geography, geo_df in df.groupby("geography", sort=True):
        geo_name = str(geography).upper()
        parquet_path = output_dir / f"{geo_name}_{name_suffix}.parquet"
        csv_path = output_dir / f"{geo_name}_{name_suffix}.csv"
        geo_df.to_parquet(parquet_path, index=False)
        geo_df.to_csv(csv_path, index=False)
        saved.extend([parquet_path, csv_path])
        print(
            f"  [{geo_name}] {len(geo_df):,} rows -> "
            f"{parquet_path.name}, {csv_path.name}"
        )
    return saved


# =============================================================================
# Build pipeline
# =============================================================================

def build_inventory_database(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
) -> pd.DataFrame:
    cfg = get_inventory_db_config(client, geos)

    print("=" * 60)
    print(f"Client : {cfg.client_code} ({cfg.client_name})")
    print(f"ID     : {cfg.client_id}")
    print(f"Geos   : {cfg.geos}")
    print(f"Sanity : {cfg.sanity_root}")
    print(f"Output : {cfg.output_dir}")
    print(
        "Ageing date: US/CA +1 day; others +0. "
        "FC: AE/IN use ageing.fc_transfer; others use afn_fc_transfer_quantity; "
        "0 -> reserved_fc_transfers"
    )
    print("=" * 60)

    frames: List[pd.DataFrame] = []
    run_log = ReportRunLog(cfg.client_code, "inventory_database")
    try:
        for geo in cfg.geos:
            try:
                cleaned = build_geography_inventory(cfg, geo)
                if not cleaned.empty:
                    frames.append(cleaned)
            except Exception as exc:  # noqa: BLE001
                print(f"[{cfg.client_code}] [{geo}] ERROR: {exc}")
                run_log.append(f"[{cfg.client_code}] [{geo}] ERROR: {exc}")

        master = (
            pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
        )
        print(
            f"\n[{cfg.client_code}] combined inventory_database "
            f"geos_ok={len(frames)}/{len(cfg.geos)} rows={len(master):,}"
        )
        run_log.append(
            f"[{cfg.client_code}] combined inventory_database "
            f"geos_ok={len(frames)}/{len(cfg.geos)} rows={len(master):,}"
        )

        alerts: dict = {}
        if not master.empty:
            print("\n>>> STEP: new SKU check")
            alerts = check_final_dataframe_new_skus(
                master,
                client=cfg.client_code,
                label="inventory_database",
                run_log=run_log,
            )

        print("\n>>> STEP: per-geography checklist")
        run_log.blank()
        run_log.section("Per-geography checklist")
        if master.empty:
            run_log.append("(no rows)")
        else:
            for geography, geo_df in master.groupby("geography", sort=True):
                code = str(geography).strip().upper()
                block = format_inventory_database_geo_section(
                    client=cfg.client_code,
                    geography=code,
                    rows=len(geo_df),
                    stock_status=None,
                    new_skus=alerts.get(code, []),
                )
                print("\n" + block)
                run_log.append(block)
                run_log.blank()

        if save_output and not master.empty:
            save_geography_outputs(master, cfg.output_dir)
    finally:
        run_log.flush()

    print("-" * 60)
    print(f"Done. Master shape: {master.shape}")
    return master


# =============================================================================
# CLI / pipeline entry
# =============================================================================

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Client-wise Amazon inventory database (manage_fba + reserved + ageing)"
    )
    parser.add_argument("--client", default=CLIENT, choices=known_clients())
    parser.add_argument("--geos", default=None, help="Comma-separated geo codes")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> pd.DataFrame:
    args = parse_args(argv)
    geos = [g.strip() for g in str(args.geos).split(",") if g.strip()] if args.geos else None
    master = build_inventory_database(
        client=args.client,
        geos=geos if geos else PROCESS_GEOS,
        save_output=not args.no_save,
    )
    if not master.empty:
        print(master.shape)
        print(master.head())
        print(master.columns.tolist())
    return master


def run(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    **_kwargs,
) -> pd.DataFrame:
    """Pipeline CLI entrypoint: run(client='ESH', geos=['US','UK'])."""
    return main(
        layouts.cli_argv(
            client=client,
            geos=list(geos) if geos else None,
        )
    )


if __name__ == "__main__":
    main()
    print_script_completed("inventory_database")
