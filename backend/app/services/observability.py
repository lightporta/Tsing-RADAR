"""Privacy-safe, bounded operational telemetry for A7.

Only route templates and aggregate HTTP outcomes are retained. Request bodies,
headers, cookies, query strings, principals, document names, and signed tokens
are deliberately outside this module's input contract.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response

logger = logging.getLogger("tsing_radar.operations")

_DURATION_BUCKETS_MS = (25, 50, 100, 250, 500, 1000, 2500, 5000)
_MAX_SERIES = 256


def _duration_bucket(duration_ms: float) -> str:
    for upper_bound in _DURATION_BUCKETS_MS:
        if duration_ms <= upper_bound:
            return f"le_{upper_bound}ms"
    return "gt_5000ms"


def _safe_route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path.startswith("/") and len(path) <= 200:
        return path
    return "unmatched"


@dataclass(frozen=True)
class Observation:
    request_id: str
    method: str
    route_template: str
    status_code: int
    duration_bucket: str


class OperationalMetrics:
    """Process-local bounded aggregates; no user-level dimensions."""

    def __init__(self, max_series: int = _MAX_SERIES) -> None:
        self._max_series = max_series
        self._lock = threading.Lock()
        self._total = 0
        self._by_status_class: Counter[str] = Counter()
        self._by_duration_bucket: Counter[str] = Counter()
        self._by_route: Counter[tuple[str, str, str]] = Counter()
        self._overflow = 0

    def record(self, observation: Observation) -> None:
        status_class = f"{observation.status_code // 100}xx"
        route_key = (
            observation.method,
            observation.route_template,
            status_class,
        )
        with self._lock:
            self._total += 1
            self._by_status_class[status_class] += 1
            self._by_duration_bucket[observation.duration_bucket] += 1
            if route_key in self._by_route or len(self._by_route) < self._max_series:
                self._by_route[route_key] += 1
            else:
                self._overflow += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            routes = [
                {
                    "method": method,
                    "route_template": route,
                    "status_class": status_class,
                    "count": count,
                }
                for (method, route, status_class), count in sorted(
                    self._by_route.items()
                )
            ]
            return {
                "schema_version": "a7-http-aggregate-v1",
                "privacy": "aggregate_no_user_dimensions",
                "total_requests": self._total,
                "by_status_class": dict(sorted(self._by_status_class.items())),
                "by_duration_bucket": dict(
                    sorted(self._by_duration_bucket.items())
                ),
                "by_route": routes,
                "overflow_series": self._overflow,
            }

    def reset_for_tests(self) -> None:
        with self._lock:
            self._total = 0
            self._by_status_class.clear()
            self._by_duration_bucket.clear()
            self._by_route.clear()
            self._overflow = 0


operational_metrics = OperationalMetrics()


async def observe_http_request(request: Request, call_next) -> Response:
    """FastAPI middleware entry point with a privacy-minimal event schema."""
    request_id = uuid.uuid4().hex
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        observation = Observation(
            request_id=request_id,
            method=request.method.upper()[:12],
            route_template=_safe_route_template(request),
            status_code=status_code,
            duration_bucket=_duration_bucket(duration_ms),
        )
        operational_metrics.record(observation)
        logger.info(
            json.dumps(
                {
                    "event": "http_request_completed",
                    "request_id": observation.request_id,
                    "method": observation.method,
                    "route_template": observation.route_template,
                    "status_code": observation.status_code,
                    "duration_bucket": observation.duration_bucket,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )


def metrics_snapshot() -> dict[str, Any]:
    """Return aggregate local telemetry for offline operator tooling."""
    return operational_metrics.snapshot()
