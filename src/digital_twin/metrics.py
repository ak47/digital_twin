from __future__ import annotations

import logging
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)

_client = None
_resolved_project_id: str | None = None


def _running_on_gcp() -> bool:
    return bool(os.environ.get("K_SERVICE") or os.environ.get("GOOGLE_CLOUD_PROJECT"))


def _gcp_project_id() -> str:
    global _resolved_project_id
    if _resolved_project_id is not None:
        return _resolved_project_id
    pid = (os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if pid:
        _resolved_project_id = pid
        return pid
    # Cloud Run sets K_SERVICE; metadata has project id even if deploy omitted env.
    if os.environ.get("K_SERVICE", "").strip():
        try:
            req = urllib.request.Request(
                "http://metadata.google.internal/computeMetadata/v1/project/project-id",
                headers={"Metadata-Flavor": "Google"},
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                pid = resp.read().decode().strip()
                if pid:
                    _resolved_project_id = pid
                    return pid
        except (OSError, urllib.error.URLError) as e:
            logger.debug("metrics metadata project-id lookup failed: %s", e)
    _resolved_project_id = ""
    return ""


def _gcp_region() -> str:
    return (os.environ.get("GCP_REGION") or os.environ.get("GOOGLE_CLOUD_REGION") or "").strip()


def _cloud_run_service() -> str:
    return (os.environ.get("K_SERVICE") or "").strip()


def _cloud_run_revision() -> str:
    return (os.environ.get("K_REVISION") or "").strip()


def _metric_type(name: str) -> str:
    name = name.strip().lstrip("/")
    if name.startswith("custom.googleapis.com/"):
        return name
    return f"custom.googleapis.com/digital_twin/{name}"


def _ensure_client():
    global _client
    if _client is not None:
        return _client
    try:
        from google.cloud import monitoring_v3  # type: ignore

        _client = monitoring_v3.MetricServiceClient()
        return _client
    except Exception as e:
        logger.debug("metrics client unavailable: %s", e)
        _client = False  # sentinel
        return None


@dataclass(frozen=True)
class MetricContext:
    project_id: str
    region: str
    service: str
    revision: str
    instance_id: str


def default_context() -> MetricContext:
    pid = _gcp_project_id()
    region = _gcp_region()
    service = _cloud_run_service()
    rev = _cloud_run_revision()
    instance = f"{socket.gethostname()}:{os.getpid()}"
    return MetricContext(
        project_id=pid,
        region=region,
        service=service,
        revision=rev,
        instance_id=instance,
    )


def _monitored_resource(ctx: MetricContext) -> tuple[str, dict[str, str]]:
    # Prefer Cloud Run monitored resource if we have the minimum labels; otherwise fall back.
    if ctx.project_id and ctx.region and ctx.service and ctx.revision:
        return (
            "cloud_run_revision",
            {
                "project_id": ctx.project_id,
                "location": ctx.region,
                "service_name": ctx.service,
                "revision_name": ctx.revision,
                "configuration_name": os.environ.get("K_CONFIGURATION", "").strip() or ctx.service,
            },
        )
    return (
        "generic_task",
        {
            "project_id": ctx.project_id or "unknown",
            "location": ctx.region or "unknown",
            "namespace": ctx.service or "digital-twin-api",
            "job": ctx.revision or "unknown",
            "task_id": ctx.instance_id,
        },
    )


_SIZE_BINS: Final[list[int]] = [0, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072]


def _bin_int(value: int, bins: list[int]) -> str:
    if value <= bins[0]:
        return f"le_{bins[0]}"
    for lo, hi in zip(bins, bins[1:], strict=False):
        if lo < value <= hi:
            return f"{lo+1}_to_{hi}"
    return f"gt_{bins[-1]}"


def _safe_label_value(s: object, *, max_len: int = 100) -> str:
    v = str(s or "").strip()
    if not v:
        return "unknown"
    if len(v) > max_len:
        return v[:max_len]
    return v


def record_latency_ms(
    metric_name: str,
    ms: float,
    *,
    labels: dict[str, str] | None = None,
    ctx: MetricContext | None = None,
) -> None:
    """
    Write a single point to a custom Cloud Monitoring metric.

    This must never raise: failures should not impact request handling.
    """
    if not _running_on_gcp():
        return

    client = _ensure_client()
    if not client:
        return

    try:
        from google.cloud import monitoring_v3  # type: ignore
        from google.protobuf import timestamp_pb2  # type: ignore

        ctx = ctx or default_context()
        rtype, rlabels = _monitored_resource(ctx)

        series = monitoring_v3.TimeSeries()
        series.metric.type = _metric_type(metric_name)
        for k, v in (labels or {}).items():
            series.metric.labels[k] = _safe_label_value(v)
        series.resource.type = rtype
        for k, v in rlabels.items():
            series.resource.labels[k] = _safe_label_value(v, max_len=256)

        now = time.time()
        end = timestamp_pb2.Timestamp()
        end.seconds = int(now)
        end.nanos = int((now - int(now)) * 1e9)

        interval = monitoring_v3.TimeInterval(end_time=end)
        point = monitoring_v3.Point(interval=interval, value=monitoring_v3.TypedValue(double_value=float(ms)))
        series.points = [point]

        project_name = f"projects/{ctx.project_id}"
        client.create_time_series(name=project_name, time_series=[series])
    except Exception as e:
        logger.debug("metrics write failed: %s", e)


def sized_label(value: int) -> str:
    return _bin_int(max(0, int(value)), _SIZE_BINS)

