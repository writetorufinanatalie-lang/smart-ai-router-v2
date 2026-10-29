"""Background evaluation jobs with safe polling metadata and unique reports."""

from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from backend.metrics_store import MetricsStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_SUITES: dict[str, dict[str, str]] = {
    "original_38": {
        "label": "Original set (38 queries)",
        "cases_file": str(PROJECT_ROOT / "tests" / "evaluation_cases.json"),
    },
    "held_out_15": {
        "label": "Held-out set (15 queries)",
        "cases_file": str(PROJECT_ROOT / "tests" / "held_out_evaluation_cases.json"),
    },
    "generalization_18": {
        "label": "Generalization set (18 queries)",
        "cases_file": str(PROJECT_ROOT / "tests" / "generalization_evaluation_cases.json"),
    },
}


class EvaluationRunBusy(RuntimeError):
    """Raised when an evaluation run is already active."""

    def __init__(self, active_run_id: str) -> None:
        super().__init__("An evaluation run is already active.")
        self.active_run_id = active_run_id


def _load_cases(path: str | Path) -> list[dict[str, Any]]:
    from scripts.run_evaluation import load_cases

    return load_cases(path)


def _run_real_evaluation(**kwargs: Any) -> dict[str, Any]:
    # Deferred to avoid importing backend.main while its app is being created.
    from scripts.run_evaluation import run_evaluation

    return run_evaluation(**kwargs)


class EvaluationJobManager:
    """Runs one suite at a time, writing each run to a new timestamped file."""

    def __init__(
        self,
        *,
        output_directory: str | Path | None = None,
        runner: Callable[..., dict[str, Any]] | None = None,
        cases_loader: Callable[[str | Path], list[dict[str, Any]]] | None = None,
        metrics_store: MetricsStore | None = None,
    ) -> None:
        self.output_directory = Path(
            output_directory or PROJECT_ROOT / "data" / "evaluation_runs"
        )
        self._runner = runner or _run_real_evaluation
        self._cases_loader = cases_loader or _load_cases
        self._metrics_store = metrics_store
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active_run_id: str | None = None

    def start(self, suite_id: str) -> dict[str, Any]:
        suite = EVALUATION_SUITES.get(suite_id)
        if suite is None:
            raise ValueError("Unknown evaluation suite.")
        # Loading validates the fixed suite and obtains the real case count; prompt
        # text is intentionally not retained in the job record.
        cases = self._cases_loader(suite["cases_file"])
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        run_id = uuid4().hex

        with self._lock:
            if self._active_run_id is not None:
                active = self._jobs.get(self._active_run_id)
                if active and active["status"] in {"queued", "running"}:
                    raise EvaluationRunBusy(self._active_run_id)
            self.output_directory.mkdir(parents=True, exist_ok=True)
            output_path = self.output_directory / f"{suite_id}_{timestamp}.json"
            # Microsecond timestamps should be unique; this guard ensures that a
            # collision never overwrites any existing report.
            suffix = 1
            while output_path.exists():
                output_path = self.output_directory / f"{suite_id}_{timestamp}_{suffix}.json"
                suffix += 1

            job = {
                "run_id": run_id,
                "suite_id": suite_id,
                "suite_label": suite["label"],
                "status": "queued",
                "completed_cases": 0,
                "total_cases": len(cases),
                "current_case_id": None,
                "results": [],
                "summary": None,
                "result_file": None,
                "error": None,
                "started_at": None,
                "finished_at": None,
            }
            self._jobs[run_id] = job
            self._active_run_id = run_id
            thread = threading.Thread(
                target=self._run,
                args=(run_id, suite_id, suite["cases_file"], output_path),
                name=f"evaluation-{suite_id}-{run_id[:8]}",
                daemon=True,
            )
            thread.start()
            return copy.deepcopy(job)

    def _run(self, run_id: str, suite_id: str, cases_file: str, output_path: Path) -> None:
        with self._lock:
            job = self._jobs[run_id]
            job["status"] = "running"
            job["started_at"] = datetime.now(timezone.utc).isoformat()

        def update_progress(update: dict[str, Any]) -> None:
            # The runner supplies only case identifiers, labels, metrics, and
            # statuses. Request, answer, and reason text are excluded.
            with self._lock:
                current = self._jobs[run_id]
                current["completed_cases"] = update["completed_cases"]
                current["current_case_id"] = update["current_case_id"]
                current["summary"] = update["summary"]
                result = update.get("latest_result")
                if result is not None:
                    current["results"].append(result)

        try:
            runner_kwargs = {
                "cases_path": cases_file,
                "output_path": output_path,
                "suite_id": suite_id,
                "progress_callback": update_progress,
            }
            if self._metrics_store is not None:
                runner_kwargs["metrics_store"] = self._metrics_store
            report = self._runner(
                **runner_kwargs,
            )
        except Exception:
            with self._lock:
                job = self._jobs[run_id]
                job["status"] = "failed"
                job["error"] = "Evaluation run failed. Check the backend log for details."
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
        else:
            with self._lock:
                job = self._jobs[run_id]
                job["status"] = report["run_status"]
                job["summary"] = report["summary"]
                job["results"] = report["results"]
                job["result_file"] = output_path.name
                job["finished_at"] = report.get("finished_at")
        finally:
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(run_id)
            return copy.deepcopy(job) if job is not None else None


def load_report(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None

