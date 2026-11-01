"""Optional MLflow experiment tracking. A tracking failure never fails training."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


def log_training_run(market: str, version: str, params: dict, metrics: dict[str, float], tags: dict[str, str],
                     artifact: Path | None = None, report: dict | None = None) -> str | None:
    s = get_settings()
    if not s.mlflow_tracking_uri:
        return None
    try:
        import json
        import tempfile

        import mlflow

        mlflow.set_tracking_uri(s.mlflow_tracking_uri)
        mlflow.set_experiment(s.mlflow_experiment)
        with mlflow.start_run(run_name=f"{market}-{version}") as run:
            mlflow.log_params({k: str(v)[:250] for k, v in params.items()})
            mlflow.log_metrics({k: float(v) for k, v in metrics.items() if v is not None})
            mlflow.set_tags(tags)
            if artifact and artifact.exists():
                mlflow.log_artifact(str(artifact))
            if report:
                with tempfile.TemporaryDirectory() as d:
                    fp = Path(d) / "walk_forward_report.json"
                    fp.write_text(json.dumps(report, default=str))
                    mlflow.log_artifact(str(fp))
            return run.info.run_id
    except Exception as exc:  # noqa: BLE001 - tracking is best effort
        log.warning("mlflow_logging_failed", error=str(exc))
        return None
