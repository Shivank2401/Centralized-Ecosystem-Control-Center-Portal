"""Run-scoped logging helpers (portal runs under runtime/runs/)."""

from __future__ import annotations

import logging
from pathlib import Path


def get_run_logger(run_id: str, run_dir: Path) -> logging.Logger:
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"pipeline_engine.run.{run_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", "").endswith("stdout.log")
        for h in logger.handlers
    ):
        fh = logging.FileHandler(run_dir / "stdout.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
        logger.addHandler(fh)
    return logger
