"""
Isolated pipeline worker process.

Usage:
    python -m backend.workers.run_worker --run-id <id>
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline_engine.executor import PipelineExecutor
from pipeline_engine.models import PipelineRunStatus
from pipeline_engine.run_manager import RunCancelled, RunManager


class _FileTee:
    """Mirror writes to console and stdout.log (for live SSE)."""

    def __init__(self, primary, path: Path) -> None:
        self.primary = primary
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, data: str) -> int:
        if not data:
            return 0
        try:
            self.primary.write(data)
            self.primary.flush()
        except Exception:
            pass
        with self.path.open("a", encoding="utf-8") as f:
            f.write(data)
        return len(data)

    def flush(self) -> None:
        try:
            self.primary.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline run worker")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    manager = RunManager()
    record = manager.get(args.run_id)
    if record is None:
        print(f"Unknown run_id: {args.run_id}", file=sys.stderr)
        return 2

    manager.set_pid(args.run_id, os.getpid())
    manager.mark_running(args.run_id)

    log_path = manager.stdout_path(args.run_id)
    sys.stdout = _FileTee(sys.__stdout__, log_path)  # type: ignore[assignment]
    sys.stderr = _FileTee(sys.__stderr__, log_path)  # type: ignore[assignment]

    executor = PipelineExecutor(run_manager=manager, track_runs=True, validate_before_run=False)

    # Avoid double-writing: structured progress goes to run.json logs only (no print).
    # Report print() still hits stdout.log via Tee.
    def _quiet_log(message: str, run_id: str | None = None) -> None:
        if run_id:
            manager.append_log(run_id, message)

    executor._log = _quiet_log  # type: ignore[method-assign]

    try:
        result = executor.run(
            client=record.client,
            geos=record.geographies,
            reports=record.reports,
            source=record.source or "api",
            run_id=args.run_id,
        )
        status = result.get("status")
        ok = status in {
            PipelineRunStatus.SUCCESS.value,
            PipelineRunStatus.CANCELLED.value,
        }
        return 0 if ok else 1
    except RunCancelled:
        manager.mark_finished(
            args.run_id, status=PipelineRunStatus.CANCELLED, error="Cancelled by user"
        )
        return 0
    except Exception as exc:
        manager.mark_finished(args.run_id, status=PipelineRunStatus.FAILED, error=str(exc))
        manager.append_log(args.run_id, traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
