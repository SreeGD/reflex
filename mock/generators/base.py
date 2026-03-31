"""Base types for data generation — anomaly injection and time-series primitives."""

from __future__ import annotations

from typing import Optional

from dataclasses import dataclass
from enum import Enum


class AnomalyType(Enum):
    NONE = "none"
    SPIKE = "spike"  # sudden jump, 3-10x normal
    DRIFT = "drift"  # gradual increase over minutes/hours
    DROP = "drop"  # sudden drop to near-zero
    SATURATION = "saturation"  # approach a hard limit asymptotically


@dataclass
class AnomalyConfig:
    anomaly_type: AnomalyType
    start_time: float  # unix epoch
    duration_seconds: float
    magnitude: float = 3.0  # multiplier for spike, target ratio for drift
    limit: Optional[float] = None  # hard limit for saturation (e.g., pool max)


@dataclass
class MetricSample:
    name: str
    labels: dict[str, str]
    value: float
    timestamp: float  # unix epoch


@dataclass
class LogEntry:
    timestamp: str  # ISO 8601
    level: str  # DEBUG, INFO, WARN, ERROR
    service: str
    instance: str
    trace_id: Optional[str]
    span_id: Optional[str]
    message: str
    logger: str
    endpoint: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    duration_ms: Optional[float] = None
    extra: Optional[dict] = None


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    operation_name: str
    service_name: str
    start_time: float  # unix epoch
    duration_ms: float
    status: str  # OK, ERROR
    attributes: dict
    events: Optional[list[dict]] = None
