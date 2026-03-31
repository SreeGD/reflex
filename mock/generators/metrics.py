"""Prometheus-style metric generator with diurnal patterns and anomaly injection."""

from __future__ import annotations

import math
import random
from typing import Generator

from mock.config import SERVICES, ServiceDef

from .base import AnomalyConfig, AnomalyType, MetricSample


class MetricsGenerator:
    """Generate realistic Prometheus metrics for all ShopFast services.

    Features:
    - Diurnal pattern (peak at 14:00 UTC, trough at 04:00)
    - Gaussian noise around baselines
    - Anomaly injection (spike, drift, drop, saturation)
    - Per-service resource metrics (DB pool, Redis pool, JVM heap)
    """

    def __init__(self, services: dict[str, ServiceDef] | None = None, seed: int = 42):
        self.services = services or SERVICES
        self.rng = random.Random(seed)
        self._anomalies: dict[str, AnomalyConfig] = {}

    def inject_anomaly(
        self,
        key: str,
        anomaly_type: AnomalyType,
        start_time: float,
        duration_seconds: float,
        magnitude: float = 3.0,
        limit: float | None = None,
    ) -> None:
        """Schedule an anomaly on a metric key (e.g., 'order-service:error_rate')."""
        self._anomalies[key] = AnomalyConfig(
            anomaly_type=anomaly_type,
            start_time=start_time,
            duration_seconds=duration_seconds,
            magnitude=magnitude,
            limit=limit,
        )

    def generate_instant(self, timestamp: float) -> list[MetricSample]:
        """Generate one scrape interval of metrics for all services."""
        samples: list[MetricSample] = []
        for svc in self.services.values():
            for i in range(svc.replicas):
                instance = f"{svc.name}-{self._pod_suffix(i)}"
                samples.extend(self._service_metrics(svc, instance, timestamp))
        return samples

    def generate_range(
        self, start: float, end: float, step: int = 15
    ) -> Generator[list[MetricSample], None, None]:
        """Generate metrics for a time range. step=15 matches Prometheus default."""
        t = start
        while t <= end:
            yield self.generate_instant(t)
            t += step

    def query(
        self, metric_name: str, labels: dict[str, str], timestamp: float
    ) -> list[MetricSample]:
        """Query a specific metric with label filters at a point in time."""
        samples = self.generate_instant(timestamp)
        return [
            s
            for s in samples
            if s.name == metric_name
            and all(s.labels.get(k) == v for k, v in labels.items())
        ]

    def query_range(
        self,
        metric_name: str,
        labels: dict[str, str],
        start: float,
        end: float,
        step: int = 15,
    ) -> list[list[MetricSample]]:
        """Range query returning filtered time series."""
        result = []
        for samples in self.generate_range(start, end, step):
            filtered = [
                s
                for s in samples
                if s.name == metric_name
                and all(s.labels.get(k) == v for k, v in labels.items())
            ]
            if filtered:
                result.append(filtered)
        return result

    def _service_metrics(
        self, svc: ServiceDef, instance: str, t: float
    ) -> list[MetricSample]:
        base_labels = {"service": svc.name, "instance": instance}
        samples: list[MetricSample] = []

        # CPU
        cpu = self._value(svc.baseline_cpu_pct, t, f"{svc.name}:cpu")
        samples.append(MetricSample("process_cpu_usage_percent", {**base_labels}, cpu, t))

        # Memory
        mem = self._value(svc.baseline_memory_mb, t, f"{svc.name}:memory")
        samples.append(
            MetricSample("process_memory_usage_bytes", {**base_labels}, mem * 1024 * 1024, t)
        )

        # Request rate
        rps = self._value(svc.baseline_rps, t, f"{svc.name}:rps")
        samples.append(
            MetricSample(
                "http_requests_total",
                {**base_labels, "method": "GET", "status_code": "200"},
                rps,
                t,
            )
        )

        # Latency
        p50 = self._value(svc.baseline_latency_p50_ms, t, f"{svc.name}:latency_p50")
        p99 = self._value(svc.baseline_latency_p99_ms, t, f"{svc.name}:latency_p99")
        samples.append(
            MetricSample(
                "http_request_duration_seconds",
                {**base_labels, "quantile": "0.5"},
                p50 / 1000,
                t,
            )
        )
        samples.append(
            MetricSample(
                "http_request_duration_seconds",
                {**base_labels, "quantile": "0.99"},
                p99 / 1000,
                t,
            )
        )

        # Error rate
        err = self._value(svc.baseline_error_rate, t, f"{svc.name}:error_rate")
        err = max(0, min(1, err))
        samples.append(
            MetricSample(
                "http_errors_total",
                {**base_labels, "error_type": "server"},
                err * rps,
                t,
            )
        )

        # DB connection pool
        if svc.db_pool_max is not None:
            active = self._value(
                (svc.db_pool_max * 0.6, svc.db_pool_max * 0.1),
                t,
                f"{svc.name}:db_pool_active",
            )
            active = max(0, min(svc.db_pool_max, active))
            samples.append(
                MetricSample("db_connection_pool_active", {**base_labels}, active, t)
            )
            samples.append(
                MetricSample(
                    "db_connection_pool_max", {**base_labels}, svc.db_pool_max, t
                )
            )
            wait = max(0, (active / svc.db_pool_max - 0.8) * 5) if active > 0 else 0
            wait = self._apply_anomaly(f"{svc.name}:db_pool_wait", wait, t)
            samples.append(
                MetricSample("db_connection_pool_wait_seconds", {**base_labels}, wait, t)
            )

        # Redis pool
        if svc.redis_pool_max is not None:
            active = self._value(
                (svc.redis_pool_max * 0.4, svc.redis_pool_max * 0.08),
                t,
                f"{svc.name}:redis_pool_active",
            )
            active = max(0, min(svc.redis_pool_max, active))
            samples.append(
                MetricSample("redis_connection_pool_active", {**base_labels}, active, t)
            )
            samples.append(
                MetricSample(
                    "redis_connection_pool_max", {**base_labels}, svc.redis_pool_max, t
                )
            )

        # JVM heap
        if svc.jvm_heap_max_mb is not None:
            heap = self._value(
                (svc.jvm_heap_max_mb * 0.55, svc.jvm_heap_max_mb * 0.05),
                t,
                f"{svc.name}:jvm_heap",
            )
            heap = max(0, min(svc.jvm_heap_max_mb, heap))
            samples.append(
                MetricSample(
                    "jvm_heap_used_bytes", {**base_labels}, heap * 1024 * 1024, t
                )
            )
            gc_pause = self._value((0.08, 0.02), t, f"{svc.name}:gc_pause")
            gc_pause = max(0, gc_pause)
            samples.append(
                MetricSample("jvm_gc_pause_seconds", {**base_labels}, gc_pause, t)
            )

        return samples

    def _value(
        self, baseline: tuple[float, float], t: float, key: str
    ) -> float:
        """Generate a value with diurnal pattern, noise, and optional anomaly."""
        mean, stddev = baseline
        normal = self._normal_value(mean, stddev, t)
        return self._apply_anomaly(key, normal, t)

    def _normal_value(self, mean: float, stddev: float, t: float) -> float:
        """Normal value with diurnal pattern and Gaussian noise."""
        hour = (t % 86400) / 3600
        diurnal = 1.0 + 0.25 * math.sin((hour - 4) * math.pi / 12)
        noise = self.rng.gauss(0, stddev)
        return max(0, mean * diurnal + noise)

    def _apply_anomaly(self, key: str, normal_value: float, t: float) -> float:
        """Apply anomaly transformation if one is active for this key."""
        anomaly = self._anomalies.get(key)
        if anomaly is None:
            return normal_value
        if t < anomaly.start_time or t > anomaly.start_time + anomaly.duration_seconds:
            return normal_value

        elapsed = t - anomaly.start_time
        progress = elapsed / anomaly.duration_seconds  # 0..1

        if anomaly.anomaly_type == AnomalyType.SPIKE:
            return normal_value * self.rng.uniform(anomaly.magnitude * 0.8, anomaly.magnitude * 1.2)
        elif anomaly.anomaly_type == AnomalyType.DRIFT:
            return normal_value * (1.0 + progress * (anomaly.magnitude - 1.0))
        elif anomaly.anomaly_type == AnomalyType.DROP:
            return normal_value * 0.05
        elif anomaly.anomaly_type == AnomalyType.SATURATION:
            limit = anomaly.limit or normal_value * anomaly.magnitude
            return limit * (1 - math.exp(-3 * progress))
        return normal_value

    def _pod_suffix(self, index: int) -> str:
        suffixes = ["x2k9p", "a7b3q", "m4n8r", "j6h2s", "w5t1v"]
        return suffixes[index % len(suffixes)]
