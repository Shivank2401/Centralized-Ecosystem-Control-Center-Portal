#!/usr/bin/env python3
"""
Back-compat wrapper — ESH shipping queue.

Prefer the shared module:
  report_script/shipping_queue/shipping_queue_report.py
  python .../shipping_queue_report.py --client ESH
"""

from __future__ import annotations

from typing import Optional, Sequence

from report_script.shipping_queue.shipping_queue_report import (  # noqa: F401
    CLIENT_CONFIGS,
    LOOKBACK_DAYS,
    UPLOAD_TO_AZURE,
    get_client_config,
    main as _main,
    run as _run,
)
from config_manager.report_helpers import print_script_completed

CLIENT = "ESH"


def run(*, client: str = CLIENT, **kwargs):
    """Pipeline entrypoint forced to ESH unless an explicit supported client is passed."""
    key = str(client or CLIENT).strip().upper()
    if key not in CLIENT_CONFIGS:
        key = CLIENT
    return _run(client=key, **kwargs)


def main(argv: Optional[Sequence[str]] = None):
    # Ensure CLI default is ESH when this wrapper is invoked directly.
    import sys

    args = list(argv) if argv is not None else list(sys.argv[1:])
    if "--client" not in args:
        args = ["--client", CLIENT, *args]
    return _main(args)


if __name__ == "__main__":
    main()
    print_script_completed("esh_shipping_queue")
