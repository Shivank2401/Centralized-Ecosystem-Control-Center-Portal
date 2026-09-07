"""Filesystem-backed run history and cancellation (v1)."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from pipeline_engine.models import PipelineRunStatus, RunRecord, utc_now_iso

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = _PROJECT_ROOT / "runtime" / "runs"


class RunCancelled(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"Run {run_id} cancelled")
        self.run_id = run_id


class RunManager:
    """One active QUEUED/RUNNING run at a time (v1)."""

    def __init__(self, runs_root: Optional[Path] = None) -> None:
        self.runs_root = Path(runs_root or DEFAULT_RUNS_ROOT)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._active_run_id: Optional[str] = None

    def _run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def _run_json(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "run.json"

    def stdout_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "stdout.log"

    def stderr_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "stderr.log"

    def create_run(
        self,
        *,
        clients: Sequence[str],
        geos: Sequence[str],
        reports: Sequence[str],
        source: str = "cli",
        reclaim_stale: bool = True,
    ) -> RunRecord:
        with self._lock:
            busy = self.get_active_run()
            if busy is not None:
                if reclaim_stale:
                    busy.status = PipelineRunStatus.FAILED
                    busy.error = "Run interrupted or superseded before completion"
                    busy.completed_at = utc_now_iso()
                    self._persist(busy)
                    if self._active_run_id == busy.run_id:
                        self._active_run_id = None
                else:
                    raise RuntimeError(
                        f"Pipeline busy. Run #{busy.run_id} is currently {busy.status.value}."
                    )
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            run_id = f"{stamp}_{uuid.uuid4().hex[:6]}"
            record = RunRecord(
                run_id=run_id,
                client=list(clients),
                geographies=list(geos),
                reports=list(reports),
                status=PipelineRunStatus.QUEUED,
                source=source,
            )
            self._persist(record)
            self._active_run_id = run_id
            return record

    def _persist(self, record: RunRecord) -> None:
        path = self._run_json(record.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2)

    def get(self, run_id: str) -> Optional[RunRecord]:
        path = self._run_json(run_id)
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as f:
            return RunRecord.from_dict(json.load(f))

    def save(self, record: RunRecord) -> None:
        with self._lock:
            self._persist(record)
            if record.status in {
                PipelineRunStatus.SUCCESS,
                PipelineRunStatus.FAILED,
                PipelineRunStatus.CANCELLED,
            }:
                if self._active_run_id == record.run_id:
                    self._active_run_id = None

    def append_log(self, run_id: str, line: str) -> None:
        record = self.get(run_id)
        if record is None:
            return
        text = line.rstrip("\n")
        if not text.strip():
            return
        record.logs.append(text)
        if len(record.logs) > 500:
            record.logs = record.logs[-500:]
        self.save(record)
        path = self.stdout_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")

    def read_stdout(self, run_id: str, *, offset: int = 0) -> Tuple[str, int]:
        path = self.stdout_path(run_id)
        if not path.exists():
            return "", offset
        data = path.read_bytes()
        if offset < 0:
            offset = 0
        if offset > len(data):
            offset = len(data)
        chunk = data[offset:].decode("utf-8", errors="replace")
        return chunk, len(data)

    def set_pid(self, run_id: str, pid: int) -> RunRecord:
        record = self.get(run_id)
        if record is None:
            raise KeyError(run_id)
        record.pid = pid
        self.save(record)
        return record

    def request_cancel(self, run_id: str) -> RunRecord:
        record = self.get(run_id)
        if record is None:
            raise KeyError(run_id)
        record.cancel_requested = True
        self.save(record)
        return record

    def is_cancel_requested(self, run_id: str) -> bool:
        record = self.get(run_id)
        return bool(record and record.cancel_requested)

    def get_active_run(self) -> Optional[RunRecord]:
        with self._lock:
            if self._active_run_id:
                record = self.get(self._active_run_id)
                if record and record.status in {
                    PipelineRunStatus.QUEUED,
                    PipelineRunStatus.RUNNING,
                }:
                    return record
                self._active_run_id = None
            for path in sorted(self.runs_root.glob("*/run.json"), reverse=True)[:50]:
                try:
                    with path.open(encoding="utf-8") as f:
                        record = RunRecord.from_dict(json.load(f))
                    if record.status in {
                        PipelineRunStatus.QUEUED,
                        PipelineRunStatus.RUNNING,
                    }:
                        self._active_run_id = record.run_id
                        return record
                except Exception:
                    continue
            return None

    def list_runs(
        self,
        *,
        limit: int = 50,
        status: Optional[str] = None,
        client: Optional[str] = None,
    ) -> List[RunRecord]:
        records: List[RunRecord] = []
        status_u = status.upper() if status else None
        client_u = client.upper() if client else None
        for path in sorted(self.runs_root.glob("*/run.json"), reverse=True):
            try:
                with path.open(encoding="utf-8") as f:
                    record = RunRecord.from_dict(json.load(f))
            except Exception:
                continue
            if status_u and record.status.value != status_u:
                continue
            if client_u and client_u not in [c.upper() for c in record.client]:
                continue
            records.append(record)
            if len(records) >= limit:
                break
        return records

    def mark_running(self, run_id: str) -> RunRecord:
        record = self.get(run_id)
        if record is None:
            raise KeyError(run_id)
        record.status = PipelineRunStatus.RUNNING
        if not record.started_at:
            record.started_at = utc_now_iso()
        self.save(record)
        return record

    def mark_progress(
        self,
        run_id: str,
        *,
        current_report: Optional[str],
        completed: Sequence[str],
        progress: float,
    ) -> RunRecord:
        record = self.get(run_id)
        if record is None:
            raise KeyError(run_id)
        record.current_report = current_report
        record.completed_reports = list(completed)
        record.progress = float(progress)
        self.save(record)
        return record

    def mark_finished(
        self,
        run_id: str,
        *,
        status: PipelineRunStatus,
        error: Optional[str] = None,
        failed_report: Optional[str] = None,
    ) -> RunRecord:
        record = self.get(run_id)
        if record is None:
            raise KeyError(run_id)
        record.status = status
        record.completed_at = utc_now_iso()
        record.error = error
        record.failed_report = failed_report
        record.current_report = None
        if status == PipelineRunStatus.SUCCESS:
            record.progress = 100.0
            record.completed_reports = list(record.reports)
        if record.started_at and record.completed_at:
            try:
                start = datetime.fromisoformat(record.started_at)
                end = datetime.fromisoformat(record.completed_at)
                record.duration_seconds = (end - start).total_seconds()
            except ValueError:
                pass
        self.save(record)
        return record
