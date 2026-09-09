"""
Download latest client COGS slices from Azure into the project folder.

Covers:
  - Clients: ESH + KNC (or --client ALL)
  - Azure (app-helper): thrive-client-ecosoulhome|kinetica/cogs/*.parquet|.csv
  - Local dest: {project_root}/cogs/{client}/  e.g. cogs/esh/, cogs/knc/
  - Optional --geos filter (e.g. UK,US,DE)

Upload/refresh Azure from Excel via want_to_update/esh_cogs.py and knc_cogs.py.

Adding a NEW client:
  1. Add client in client.yaml + COGS Azure container/prefix in cogs_io
  2. Register in CLIENT_CONFIGS / SUPPORTED_CLIENTS below
  3. List the client on this report in report.yaml

Style: step-by-step prints (>>> STEP). Download logic lives in cogs_io (unchanged).

Run:
    python report_script/helper_files_nd_saving/download_cogs.py
    python report_script/helper_files_nd_saving/download_cogs.py --client ESH
    python report_script/helper_files_nd_saving/download_cogs.py --client KNC --geos UK,DE
    python report_script/helper_files_nd_saving/download_cogs.py --client ALL
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager.report_helpers import print_script_completed
from report_script.want_to_update import cogs_io


# =============================================================================
# Client configuration
# =============================================================================

CLIENT = "ESH"
SUPPORTED_CLIENTS = ("ESH", "KNC")

CLIENT_CONFIGS: Dict[str, Callable[[], str]] = {
    "ESH": lambda: "ESH",
    "KNC": lambda: "KNC",
}


def get_client_key(client: str) -> str:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"download_cogs supports {known} only (got '{client}')")
    return CLIENT_CONFIGS[key]()


# =============================================================================
# Pipeline / CLI
# =============================================================================

def run(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    **_kwargs,
) -> List[Path]:
    """
    Pipeline entrypoint.

    Downloads COGS for the selected client into ``cogs/{client}/``.
    When the pipeline passes multiple clients, invoke once per client.
    """
    key = get_client_key(client)
    print(f"\n>>> STEP: download COGS from Azure — client={key}")
    if geos:
        print(f"  geos filter: {', '.join(str(g) for g in geos)}")
    saved = cogs_io.download_cogs_from_azure(key, geos=geos)
    print(f">>> STEP: done — {len(saved)} file(s) for {key}")
    for path in saved:
        print(f"  → {path}")
    return saved


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download latest COGS from Azure -> cogs/{client}/"
    )
    p.add_argument(
        "--client",
        default=CLIENT,
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


if __name__ == "__main__":
    main()
    print_script_completed("download_cogs")
