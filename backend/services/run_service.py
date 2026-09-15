"""Run orchestration: validate, queue, spawn worker, cancel."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pipeline_engine.models import PipelineRunStatus, RunRecord
from pipeline_engine.run_manager import RunManager
from pipeline_engine.validation import PipelineValidator

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_AUDIT_PATH = _PROJECT_ROOT / "runtime" / "audit.log"


def _audit(message: str) -> None:
    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{stamp} UTC  {message}\n")


class RunService:
    def __init__(
        self,
        run_manager: Optional[RunManager] = None,
        validator: Optional[PipelineValidator] = None,
    ) -> None:
        self.run_manager = run_manager or RunManager()
        self.validator = validator or PipelineValidator()
        self._children: Dict[str, subprocess.Popen] = {}

    def refresh(self) -> None:
        """Reload report.yaml into the validator registry (keep in sync with portal edits)."""
        if hasattr(self.validator, "registry") and hasattr(self.validator.registry, "refresh"):
            self.validator.registry.refresh()

    def create_and_start(
        self,
        *,
        clients: Sequence[str],
        geos: Sequence[str],
        reports: Sequence[str],
        source: str = "api",
    ) -> RunRecord:
        # Always re-read YAML so newly registered reports (e.g. shopify_sell_thru)
        # are visible without restarting portal.py.
        self.refresh()

        clients_u = [c.strip().upper() for c in clients]
        geos_u = [g.strip().upper() for g in geos]
        reports_l = [r.strip().lower() for r in reports]

        if not clients_u or not geos_u or not reports_l:
            raise ValueError("clients, geos, and reports are required")

        validation = self.validator.validate_run(clients_u, geos_u, reports_l)
        if not validation.ok:
            errors = [c.message for c in validation.checks if not c.ok and c.level == "ERROR"]
            raise ValueError("Validation failed: " + "; ".join(errors))

        busy = self.run_manager.get_active_run()
        if busy is not None:
            # Reclaim if worker PID is gone (crash / kill outside portal)
            if busy.pid and not self._pid_alive(busy.pid):
                self.run_manager.mark_finished(
                    busy.run_id,
                    status=PipelineRunStatus.FAILED,
                    error="Worker process exited unexpectedly",
                )
                busy = None
            else:
                raise RuntimeError(
                    f"Pipeline busy. Run #{busy.run_id} is currently {busy.status.value}."
                )

        record = self.run_manager.create_run(
            clients=clients_u,
            geos=geos_u,
            reports=reports_l,
            source=source,
            reclaim_stale=False,
        )
        self._spawn(record.run_id)
        _audit(
            f'Pipeline started run_id={record.run_id} clients={clients_u} '
            f'geos={geos_u} reports={reports_l}'
        )
        return self.run_manager.get(record.run_id) or record

    def _pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if sys.platform == "win32":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return str(pid) in (result.stdout or "")
            except OSError:
                return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _spawn(self, run_id: str) -> None:
        cmd = [
            sys.executable,
            "-m",
            "backend.workers.run_worker",
            "--run-id",
            run_id,
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=str(_PROJECT_ROOT),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._children[run_id] = proc
        self.run_manager.set_pid(run_id, proc.pid)

    def get(self, run_id: str) -> Optional[RunRecord]:
        return self.run_manager.get(run_id)

    def list_runs(
        self,
        *,
        limit: int = 50,
        status: Optional[str] = None,
        client: Optional[str] = None,
    ) -> List[RunRecord]:
        return self.run_manager.list_runs(limit=limit, status=status, client=client)

    def get_active(self) -> Optional[RunRecord]:
        return self.run_manager.get_active_run()

    def cancel(self, run_id: str) -> RunRecord:
        record = self.run_manager.get(run_id)
        if record is None:
            raise KeyError(run_id)
        if record.status not in {PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING}:
            raise RuntimeError(f"Run {run_id} is already {record.status.value}")

        self.run_manager.request_cancel(run_id)
        pid = record.pid
        proc = self._children.get(run_id)

        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        elif pid:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        check=False,
                        capture_output=True,
                    )
                else:
                    os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

        finished = self.run_manager.mark_finished(
            run_id,
            status=PipelineRunStatus.CANCELLED,
            error="Cancelled by user",
        )
        self.run_manager.append_log(run_id, "[portal] Cancel requested — worker terminated")
        _audit(f"Pipeline cancelled run_id={run_id}")
        self._children.pop(run_id, None)
        return finished

    def logs(self, run_id: str, *, offset: int = 0) -> Dict[str, Any]:
        record = self.run_manager.get(run_id)
        if record is None:
            raise KeyError(run_id)
        text, new_offset = self.run_manager.read_stdout(run_id, offset=offset)
        return {
            "run_id": run_id,
            "offset": new_offset,
            "text": text,
            "status": record.status.value,
            "progress": record.progress,
            "current_report": record.current_report,
            "completed_reports": record.completed_reports,
        }

    def to_dict(self, record: RunRecord) -> Dict[str, Any]:
        return record.to_dict()


# Process-wide singleton used by API routes
run_service = RunService()
