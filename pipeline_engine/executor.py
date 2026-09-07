"""Execute reports via existing report_script modules (no ETL duplication)."""

from __future__ import annotations

import importlib
import traceback
from typing import Any, Callable, List, Optional, Sequence

from pipeline_engine.models import PipelineRunStatus, ReportResult
from pipeline_engine.registry import ConfigRegistry
from pipeline_engine.run_manager import RunCancelled, RunManager
from pipeline_engine.validation import PipelineValidator


def adapt_result(raw: Any) -> ReportResult:
    if isinstance(raw, ReportResult):
        return raw
    if raw is None:
        return ReportResult(status="success", message="Completed", raw=raw)
    if isinstance(raw, dict) and "status" in raw:
        return ReportResult(
            status=str(raw.get("status", "success")),
            message=str(raw.get("message", "")),
            outputs=list(raw.get("outputs") or []),
            stats=dict(raw.get("stats") or {}),
            raw=raw,
        )
    return ReportResult(status="success", message="Completed", raw=raw)


class PipelineExecutor:
    """
    Programmatic entry point shared by CLI and API.

        executor = PipelineExecutor()
        executor.run(client="ESH", geos=["US"], reports=["manage_fba"])
    """

    def __init__(
        self,
        registry: Optional[ConfigRegistry] = None,
        run_manager: Optional[RunManager] = None,
        validator: Optional[PipelineValidator] = None,
        *,
        track_runs: bool = True,
        validate_before_run: bool = False,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.registry = registry or ConfigRegistry()
        self.run_manager = run_manager or RunManager()
        self.validator = validator or PipelineValidator(self.registry)
        self.track_runs = track_runs
        self.validate_before_run = validate_before_run
        self.on_log = on_log

    def _log(self, message: str, run_id: Optional[str] = None) -> None:
        print(message)
        if self.on_log:
            self.on_log(message)
        if run_id and self.track_runs:
            self.run_manager.append_log(run_id, message)

    def import_and_run(self, module_path: str, **kwargs: Any) -> ReportResult:
        if not module_path:
            self._log("  [skip] no module wired yet")
            return ReportResult(status="skipped", message="no module wired")
        try:
            mod = importlib.import_module(module_path)
        except ModuleNotFoundError as exc:
            self._log(f"  [skip] cannot import {module_path}: {exc}")
            return ReportResult(status="skipped", message=str(exc))
        runner = getattr(mod, "run", None) or getattr(mod, "main", None)
        if runner is None:
            self._log(f"  [skip] {module_path} has no run()/main()")
            return ReportResult(status="skipped", message="no run()/main()")
        try:
            raw = runner(**kwargs)
        except TypeError:
            raw = runner()
        return adapt_result(raw)

    def run_reports(
        self,
        clients: Sequence[str],
        geos: Sequence[str],
        reports: Sequence[str],
        *,
        run_id: Optional[str] = None,
    ) -> List[ReportResult]:
        reports_cfg = self.registry.all_reports()
        total = len(reports)
        results: List[ReportResult] = []
        completed: List[str] = []

        for step, report in enumerate(reports, start=1):
            if run_id and self.track_runs and self.run_manager.is_cancel_requested(run_id):
                raise RunCancelled(run_id)

            meta = reports_cfg.get(report)
            if not meta or not meta.get("enabled", True):
                self._log(f"  [{step}/{total}] [skip] report {report}", run_id)
                continue

            label = self.registry.report_label(report)
            self._log(f"\n--- Sequence step {step}/{total}: {label} [{report}] ---", run_id)
            if run_id and self.track_runs:
                self.run_manager.mark_progress(
                    run_id,
                    current_report=report,
                    completed=completed,
                    progress=((step - 1) / total) * 100.0 if total else 0.0,
                )

            for client in clients:
                if run_id and self.track_runs and self.run_manager.is_cancel_requested(run_id):
                    raise RunCancelled(run_id)
                if not self.registry.matches_clients(meta, [client]):
                    self._log(f"  [skip] {client} / {report} (client-specific report)", run_id)
                    continue
                allowed = set(self.registry.geographies(client))
                client_geos = [g for g in geos if g in allowed]
                if not client_geos:
                    self._log(f"  [skip] {client}: no matching geographies in selection", run_id)
                    continue
                self._log(f"  {client} / {report} / geos={client_geos}", run_id)
                results.append(
                    self.import_and_run(meta.get("module"), client=client, geos=client_geos)
                )

            completed.append(report)
            if run_id and self.track_runs:
                self.run_manager.mark_progress(
                    run_id,
                    current_report=None,
                    completed=completed,
                    progress=(step / total) * 100.0 if total else 100.0,
                )
        return results

    def run(
        self,
        *,
        client: str | Sequence[str],
        geos: Sequence[str] | None = None,
        reports: Sequence[str] | None = None,
        report: str | Sequence[str] | None = None,
        source: str = "cli",
        track: Optional[bool] = None,
        run_id: Optional[str] = None,
    ) -> dict:
        if isinstance(client, str):
            clients = [client.strip().upper()]
        else:
            clients = [c.strip().upper() for c in client]

        geo_list = [g.strip().upper() for g in (geos or [])]
        if not geo_list:
            geo_list = self.registry.all_geo_codes()

        if reports is not None:
            report_list = [r.strip().lower() for r in reports]
        elif report is not None:
            if isinstance(report, str):
                report_list = [r.strip().lower() for r in report.split(",") if r.strip()]
            else:
                report_list = [r.strip().lower() for r in report]
        else:
            raise ValueError("Provide reports= or report=")

        track_runs = self.track_runs if track is None else track
        active_run_id: Optional[str] = run_id

        self._log("\nStarting pipeline...")
        self._log(f"  clients  = {clients}")
        self._log(f"  geos     = {geo_list}")
        self._log(f"  sequence = {[self.registry.report_label(r) for r in report_list]}")

        for c in clients:
            self.registry.get_client(c)

        if self.validate_before_run:
            report_validation = self.validator.validate_run(clients, geo_list, report_list)
            if not report_validation.ok:
                errors = [
                    c.message for c in report_validation.checks if not c.ok and c.level == "ERROR"
                ]
                raise ValueError("Validation failed:\n  - " + "\n  - ".join(errors))

        try:
            if track_runs:
                if active_run_id:
                    existing = self.run_manager.get(active_run_id)
                    if existing is None:
                        raise KeyError(f"Unknown run_id: {active_run_id}")
                    self.run_manager.mark_running(active_run_id)
                else:
                    record = self.run_manager.create_run(
                        clients=clients, geos=geo_list, reports=report_list, source=source
                    )
                    active_run_id = record.run_id
                    self.run_manager.mark_running(active_run_id)
                self._log(f"  run_id   = {active_run_id}", active_run_id)

            results = self.run_reports(clients, geo_list, report_list, run_id=active_run_id)
            if track_runs and active_run_id:
                self.run_manager.mark_finished(active_run_id, status=PipelineRunStatus.SUCCESS)
            self._log("\nPipeline finished.")
            return {
                "run_id": active_run_id,
                "status": PipelineRunStatus.SUCCESS.value,
                "clients": clients,
                "geos": geo_list,
                "reports": report_list,
                "results": [r.to_dict() for r in results],
            }
        except RunCancelled as exc:
            if track_runs and active_run_id:
                self.run_manager.mark_finished(
                    active_run_id,
                    status=PipelineRunStatus.CANCELLED,
                    error="Cancelled by user",
                )
                self._log("\nPipeline cancelled.", active_run_id)
            return {
                "run_id": active_run_id,
                "status": PipelineRunStatus.CANCELLED.value,
                "clients": clients,
                "geos": geo_list,
                "reports": report_list,
                "results": [],
                "error": str(exc),
            }
        except Exception as exc:
            if track_runs and active_run_id:
                self.run_manager.mark_finished(
                    active_run_id, status=PipelineRunStatus.FAILED, error=str(exc)
                )
                self._log(f"\nPipeline failed: {exc}", active_run_id)
                self._log(traceback.format_exc(), active_run_id)
            raise

    def execute(
        self,
        clients: Sequence[str],
        geos: Sequence[str],
        reports: Sequence[str],
        *,
        source: str = "cli",
        track: Optional[bool] = None,
    ) -> dict:
        return self.run(
            client=clients, geos=geos, reports=reports, source=source, track=track
        )
