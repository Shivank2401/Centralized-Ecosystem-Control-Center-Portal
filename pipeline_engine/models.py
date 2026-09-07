"""Shared models for pipeline runs and report results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class PipelineRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class ReportResult:
    status: str = "success"
    message: str = ""
    outputs: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        return data


@dataclass
class RunRecord:
    run_id: str
    client: List[str]
    geographies: List[str]
    reports: List[str]
    status: PipelineRunStatus = PipelineRunStatus.QUEUED
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    current_report: Optional[str] = None
    progress: float = 0.0
    completed_reports: List[str] = field(default_factory=list)
    failed_report: Optional[str] = None
    error: Optional[str] = None
    outputs: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    source: str = "cli"
    pid: Optional[int] = None
    cancel_requested: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = (
            self.status.value if isinstance(self.status, PipelineRunStatus) else self.status
        )
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunRecord":
        status = data.get("status", PipelineRunStatus.QUEUED)
        if isinstance(status, str):
            status = PipelineRunStatus(status)
        return cls(
            run_id=str(data["run_id"]),
            client=list(data.get("client") or data.get("clients") or []),
            geographies=list(data.get("geographies") or data.get("geos") or []),
            reports=list(data.get("reports") or []),
            status=status,
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            duration_seconds=data.get("duration_seconds"),
            current_report=data.get("current_report"),
            progress=float(data.get("progress") or 0.0),
            completed_reports=list(data.get("completed_reports") or []),
            failed_report=data.get("failed_report"),
            error=data.get("error"),
            outputs=list(data.get("outputs") or []),
            logs=list(data.get("logs") or []),
            source=str(data.get("source") or "cli"),
            pid=data.get("pid"),
            cancel_requested=bool(data.get("cancel_requested", False)),
        )
