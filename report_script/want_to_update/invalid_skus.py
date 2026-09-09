"""
Manage per-client DEFAULT_INVALID_SKUS stored in JSON.

Covers:
  - Clients: ESH, KNC, EMM — interactive view/add menu
  - Storage: config_manager/invalid_skus.json
  - Consumed by esh_sku_cleaning / knc_sku_cleaning during sanity SKU clean

Run:
    python report_script/want_to_update/invalid_skus.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager.invalid_skus_store import (
    SUPPORTED_CLIENTS,
    add_invalid_skus,
    invalid_skus_path,
    list_invalid_skus,
    parse_sku_blob,
)


def _prompt_client() -> Optional[str]:
    print("\nClients:")
    for i, code in enumerate(SUPPORTED_CLIENTS, start=1):
        print(f"  {i}. {code}")
    raw = input("\nSelect client [1-3 / ESH / KNC / EMM] (Enter=cancel): ").strip()
    if not raw:
        return None
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(SUPPORTED_CLIENTS):
            return SUPPORTED_CLIENTS[idx - 1]
        print(f"Invalid index: {raw}")
        return None
    code = raw.strip().upper()
    if code in SUPPORTED_CLIENTS:
        return code
    print(f"Unknown client: {raw}")
    return None


def _view() -> None:
    client = _prompt_client()
    if not client:
        return
    skus = list_invalid_skus(client, force_reload=True)
    print(f"\n[{client}] DEFAULT_INVALID_SKUS ({len(skus)}):")
    print(f"  file: {invalid_skus_path()}")
    if not skus:
        print("  (empty)")
        return
    for sku in skus:
        print(f"  - {sku}")


def _read_paste() -> List[str]:
    print(
        "\nPaste SKUs (one per line, or space/comma separated).\n"
        "Finish with an empty line (or type DONE):\n"
    )
    lines: List[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip() or line.strip().upper() == "DONE":
            break
        lines.append(line)
    return parse_sku_blob("\n".join(lines))


def _add() -> None:
    client = _prompt_client()
    if not client:
        return
    skus = _read_paste()
    if not skus:
        print("No SKUs entered — nothing to add.")
        return
    print(f"\nAbout to add {len(skus)} SKU(s) for {client}:")
    for sku in skus[:30]:
        print(f"  + {sku}")
    if len(skus) > 30:
        print(f"  ... +{len(skus) - 30} more")
    confirm = input("\nConfirm add? [y/N]: ").strip().lower()
    if confirm not in {"y", "yes"}:
        print("Cancelled.")
        return
    result = add_invalid_skus(client, skus)
    print(
        f"\n[{result['client']}] added={len(result['added'])} "
        f"skipped_existing={len(result['skipped_existing'])} "
        f"total={result['total']}"
    )
    print(f"  saved: {result['path']}")


def interactive_menu() -> None:
    print(f"Invalid SKUs store: {invalid_skus_path()}")
    while True:
        print(
            """
Invalid SKUs manager
1. View DEFAULT_INVALID_SKUS
2. Add DEFAULT_INVALID_SKUS
3. Exit
""".rstrip()
        )
        choice = input("\nSelect [1-3]: ").strip()
        if choice in {"1"}:
            _view()
        elif choice in {"2"}:
            _add()
        elif choice in {"3", "q", "Q", "exit", "EXIT"}:
            print("Done.")
            return
        else:
            print(f"Invalid choice: {choice}")


def run(*, client: str | None = None, **_kwargs) -> None:
    """Pipeline entry — always opens the interactive manager."""
    _ = client
    interactive_menu()


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="View / add per-client invalid SKUs (JSON)")
    p.add_argument("--client", default="", help="Optional: ESH / KNC / EMM (still opens menu)")
    p.add_argument("--view", action="store_true", help="View SKUs for --client and exit")
    p.add_argument(
        "--add",
        default="",
        help="Comma/space separated SKUs to add for --client (non-interactive)",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parse_args(argv)
    client = str(args.client).strip().upper() or None
    if args.view:
        if not client:
            raise SystemExit("--view requires --client")
        skus = list_invalid_skus(client, force_reload=True)
        print(f"[{client}] {len(skus)} invalid SKU(s) @ {invalid_skus_path()}")
        for sku in skus:
            print(sku)
        return
    if str(args.add).strip():
        if not client:
            raise SystemExit("--add requires --client")
        skus = parse_sku_blob(str(args.add))
        result = add_invalid_skus(client, skus)
        print(
            f"[{result['client']}] added={len(result['added'])} "
            f"skipped={len(result['skipped_existing'])} total={result['total']}"
        )
        return
    interactive_menu()


from config_manager.report_helpers import print_script_completed

if __name__ == "__main__":
    main()
    print_script_completed('invalid_skus')
