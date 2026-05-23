"""Metric Tracker — tracks performance and quality metrics across the system."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """A single metric data point."""

    value: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    labels: dict[str, str] = field(default_factory=dict)


class MetricTracker:
    """Collects and aggregates metrics from all agents and infrastructure.

    Tracks counters, gauges, and histograms for:
    - Task execution (count, success rate, duration)
    - Agent performance (by type and instance)
    - Knowledge quality (confidence, usefulness)
    - Policy compliance rates
    - Skill progression
    """

    def __init__(self) -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._series: dict[str, list[MetricPoint]] = defaultdict(list)
        self._max_series_len = 10000

    def increment(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        """Increment a counter metric."""
        key = self._key(name, labels)
        self._counters[key] += value

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Set a gauge metric to an absolute value."""
        key = self._key(name, labels)
        self._gauges[key] = value

    def record(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record a data point in a time series."""
        key = self._key(name, labels)
        series = self._series[key]
        series.append(MetricPoint(value=value, labels=labels or {}))
        if len(series) > self._max_series_len:
            self._series[key] = series[-self._max_series_len :]

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = self._key(name, labels)
        return self._counters.get(key, 0.0)

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = self._key(name, labels)
        return self._gauges.get(key, 0.0)

    def get_series(
        self, name: str, labels: dict[str, str] | None = None, limit: int = 100
    ) -> list[MetricPoint]:
        key = self._key(name, labels)
        return self._series.get(key, [])[-limit:]

    def average(self, name: str, labels: dict[str, str] | None = None, window: int = 100) -> float:
        """Get the rolling average of a time series."""
        points = self.get_series(name, labels, limit=window)
        if not points:
            return 0.0
        return sum(p.value for p in points) / len(points)

    def summary(self) -> dict:
        """Return a summary of all tracked metrics."""
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "series_keys": list(self._series.keys()),
            "total_data_points": sum(len(s) for s in self._series.values()),
        }

    @staticmethod
    def _key(name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
