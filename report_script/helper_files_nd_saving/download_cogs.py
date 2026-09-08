"""
Download latest client COGS slices from Azure into the project folder.

Destination:
  {project_root}/cogs/{client}/  e.g. cogs/esh/, cogs/knc/

Azure source (container app-helper unless overridden):
  ESH -> thrive-client-ecosoulhome/cogs/*.parquet|.csv
  KNC -> thrive-client-kinetica/cogs/*.parquet|.csv

Upload / refresh Azure from Excel via want_to_update:
  report_script/want_to_update/esh_cogs.py
  report_script/want_to_update/knc_cogs.py

Run:
  python report_script/supply_chain/d_download_cogs.py
  python report_script/supply_chain/d_download_cogs.py --client ESH
  python report_script/supply_chain/d_download_cogs.py --client KNC --geos UK,DE
  # or via run_pipeline.py -> Stage: supply_chain -> Download COGS
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from report_script.want_to_update import cogs_io

SUPPORTED_CLIENTS = ("ESH", "KNC")


def run(
    *,
    client: str = "ESH",
    geos: Optional[Sequence[str]] = None,
    **_kwargs,
) -> List[Path]:
    """
    Pipeline entrypoint.

    Downloads COGS for the selected client into ``cogs/{client}/``.
    When the pipeline passes multiple clients, invoke once per client.
    """
    key = str(client).strip().upper()
    if key not in SUPPORTED_CLIENTS:
        raise ValueError(
            f"d_download_cogs supports clients {SUPPORTED_CLIENTS}, got {client!r}"
        )
    print(f"\nDownload COGS from Azure — client={key}")
    return cogs_io.download_cogs_from_azure(key, geos=geos)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download latest COGS from Azure -> cogs/{client}/"
    )
    p.add_argument(
        "--client",
        default="ESH",
        help="ESH or KNC (default ESH). Pass ALL to download both.",
    )
    p.add_argument(
        "--geos",
        default="",
        help="Optional comma-separated geo filter, e.g. UK,US,DE",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> List[Path]:
    args = _parse_args(argv)
    geos = [g.strip() for g in str(args.geos).split(",") if g.strip()] or None
    raw = str(args.client).strip().upper()
    clients = list(SUPPORTED_CLIENTS) if raw in {"ALL", "*"} else [raw]
    saved: List[Path] = []
    for c in clients:
        saved.extend(run(client=c, geos=geos))
    return saved


from config_manager.report_helpers import print_script_completed

if __name__ == "__main__":
    main()
    print_script_completed('download_cogs')
