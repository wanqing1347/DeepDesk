import math
import threading
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

_HISTOGRAM_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)


@dataclass(slots=True)
class _HistogramSample:
    count: int = 0
    total: float = 0.0
    buckets: list[int] = field(default_factory=lambda: [0] * len(_HISTOGRAM_BUCKETS))


@dataclass(slots=True, frozen=True)
class MetricsContext:
    registry: "MetricsRegistry"
    agent_type: str


_metrics_context_var: ContextVar[MetricsContext | None] = ContextVar("metrics_context", default=None)


class MetricsRegistry:
    """Small in-process Prometheus text registry without an extra runtime dependency."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], _HistogramSample] = {}

    def increment(self, name: str, *, labels: dict[str, str], value: float = 1.0) -> None:
        key = (name, self._label_key(labels))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def observe(self, name: str, value: float, *, labels: dict[str, str]) -> None:
        key = (name, self._label_key(labels))
        with self._lock:
            sample = self._histograms.setdefault(key, _HistogramSample())
            sample.count += 1
            sample.total += value
            for index, bucket in enumerate(_HISTOGRAM_BUCKETS):
                if value <= bucket:
                    sample.buckets[index] += 1

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = sorted(self._counters.items())
            histograms = sorted(self._histograms.items())

        counter_names = sorted({name for (name, _), _ in counters})
        for name in counter_names:
            lines.append(f"# TYPE {name} counter")
            for (metric_name, labels), value in counters:
                if metric_name != name:
                    continue
                lines.append(f"{name}{self._format_labels(labels)} {self._format_number(value)}")

        histogram_names = sorted({name for (name, _), _ in histograms})
        for name in histogram_names:
            lines.append(f"# TYPE {name} histogram")
            for (metric_name, labels), sample in histograms:
                if metric_name != name:
                    continue
                for bucket, count in zip(_HISTOGRAM_BUCKETS, sample.buckets, strict=True):
                    bucket_labels = (*labels, ("le", self._format_bucket(bucket)))
                    lines.append(f"{name}_bucket{self._format_labels(bucket_labels)} {count}")
                infinite_labels = (*labels, ("le", "+Inf"))
                lines.append(f"{name}_bucket{self._format_labels(infinite_labels)} {sample.count}")
                lines.append(f"{name}_sum{self._format_labels(labels)} {self._format_number(sample.total)}")
                lines.append(f"{name}_count{self._format_labels(labels)} {sample.count}")

        return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def _label_key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((str(name), str(value)) for name, value in labels.items()))

    @staticmethod
    def _escape_label(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

    @classmethod
    def _format_labels(cls, labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        body = ",".join(f'{name}="{cls._escape_label(value)}"' for name, value in labels)
        return "{" + body + "}"

    @staticmethod
    def _format_bucket(value: float) -> str:
        if value.is_integer():
            return str(int(value))
        return format(value, "g")

    @staticmethod
    def _format_number(value: float) -> str:
        if math.isfinite(value):
            return format(value, ".12g")
        return "0"


def bind_metrics_context(registry: MetricsRegistry, agent_type: str) -> Token[MetricsContext | None]:
    return _metrics_context_var.set(MetricsContext(registry=registry, agent_type=agent_type))


def reset_metrics_context(token: Token[MetricsContext | None]) -> None:
    _metrics_context_var.reset(token)


def current_metrics_context() -> MetricsContext | None:
    return _metrics_context_var.get()


def record_agent_error(code: str) -> None:
    context = current_metrics_context()
    if context is None or not context.agent_type:
        return
    context.registry.increment(
        "deepdesk_agent_errors_total",
        labels={"agent_type": context.agent_type, "code": code or "UNKNOWN"},
    )


def record_provider_retry(provider: str, operation: str) -> None:
    context = current_metrics_context()
    if context is None:
        return
    context.registry.increment(
        "deepdesk_agent_provider_retries_total",
        labels={
            "agent_type": context.agent_type or "unknown",
            "provider": provider,
            "operation": operation,
        },
    )


def record_tool_call(tool_name: str, *, started_at: float, outcome: str) -> None:
    context = current_metrics_context()
    if context is None or not context.agent_type:
        return
    duration_seconds = max(0.0, time.perf_counter() - started_at)
    labels = {
        "agent_type": context.agent_type,
        "tool_name": tool_name or "unknown",
        "outcome": outcome,
    }
    context.registry.increment("deepdesk_agent_tool_calls_total", labels=labels)
    context.registry.observe("deepdesk_agent_tool_duration_seconds", duration_seconds, labels=labels)
