"""Per-language telemetry defaults — how a repo emits, in its own idiom.

Nothing here is exotic: OpenTelemetry is the one instrumentation API every one
of these ecosystems has, and its wire format (OTLP) is accepted by every backend
a team is likely to already run. So the pipeline can name the exact package and
the exact environment variables a task must wire, without knowing or caring
which vendor is on the other end of the collector.

Unknown languages fall back to a vendor-neutral description rather than
inventing a package that does not exist for them.
"""

from __future__ import annotations

from typing import NamedTuple, Optional


class TelemetryStack(NamedTuple):
    """The instrumentation a language uses, and how it is turned on."""

    package: str  # what to add to the manifest
    api: str  # what the code calls
    autoinstrument: str = ""  # the zero-code option, when the ecosystem has one
    notes: str = ""

    def render(self) -> str:
        extra = f" · {self.autoinstrument}" if self.autoinstrument else ""
        return f"{self.api} via {self.package}{extra}"


#: Environment every instrumented service reads, whatever the language. Values
#: are deployment concerns and never appear in code or in this repository.
OTEL_ENVIRONMENT: tuple[tuple[str, str], ...] = (
    ("OTEL_SERVICE_NAME", "the service this signal belongs to"),
    ("OTEL_EXPORTER_OTLP_ENDPOINT", "collector URL — set per environment"),
    ("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment, service.version"),
    ("OTEL_TRACES_SAMPLER_ARG", "sampling ratio; 1.0 only in non-production"),
)

_STACKS: dict[str, TelemetryStack] = {
    "python": TelemetryStack(
        "opentelemetry-sdk~=1.27 + opentelemetry-exporter-otlp~=1.27",
        "opentelemetry.metrics / trace",
        "opentelemetry-instrument <cmd>",
    ),
    "typescript": TelemetryStack(
        "@opentelemetry/sdk-node ^0.53",
        "@opentelemetry/api",
        "--require @opentelemetry/auto-instrumentations-node/register",
    ),
    "javascript": TelemetryStack(
        "@opentelemetry/sdk-node ^0.53",
        "@opentelemetry/api",
        "--require @opentelemetry/auto-instrumentations-node/register",
    ),
    "go": TelemetryStack("go.opentelemetry.io/otel", "otel.Meter / otel.Tracer"),
    "java": TelemetryStack(
        "io.opentelemetry:opentelemetry-sdk",
        "io.opentelemetry.api",
        "-javaagent:opentelemetry-javaagent.jar",
    ),
    "kotlin": TelemetryStack(
        "io.opentelemetry:opentelemetry-sdk",
        "io.opentelemetry.api",
        "-javaagent:opentelemetry-javaagent.jar",
    ),
    "csharp": TelemetryStack(
        "OpenTelemetry.Extensions.Hosting",
        "System.Diagnostics.Metrics / ActivitySource",
    ),
    "rust": TelemetryStack("opentelemetry + tracing-opentelemetry", "tracing macros"),
    "ruby": TelemetryStack(
        "opentelemetry-sdk", "OpenTelemetry.tracer_provider", "opentelemetry-instrumentation-all"
    ),
    "php": TelemetryStack("open-telemetry/sdk", "OpenTelemetry\\API", "otel php extension"),
    "swift": TelemetryStack("opentelemetry-swift", "OpenTelemetryApi"),
    "scala": TelemetryStack("io.opentelemetry:opentelemetry-sdk", "otel4s / Java API"),
    "elixir": TelemetryStack("opentelemetry + opentelemetry_exporter", ":telemetry handlers"),
    "cpp": TelemetryStack("opentelemetry-cpp", "opentelemetry::metrics"),
    "terraform": TelemetryStack(
        "provider-native monitors",
        "the monitoring provider's resources",
        notes="alerts and dashboards are themselves code here — commit them",
    ),
    "sql": TelemetryStack(
        "warehouse query history",
        "scheduled freshness and row-count checks",
        notes="freshness and volume are the signals; there is no process to trace",
    ),
    "shell": TelemetryStack(
        "exit codes + structured stderr",
        "log lines a collector can parse",
        notes="a script's signal is its exit status and its duration",
    ),
}

_FALLBACK = TelemetryStack(
    "an OpenTelemetry SDK for this language, or the platform's native client",
    "vendor-neutral OTLP export",
    notes="no first-party OTel SDK is assumed for this ecosystem",
)


def telemetry_for(language: Optional[str]) -> TelemetryStack:
    """The instrumentation stack for a language, never a guess dressed as fact."""
    return _STACKS.get((language or "").lower(), _FALLBACK)


def stack_summary(language: Optional[str], display_name: str = "") -> str:
    stack = telemetry_for(language)
    name = display_name or language
    if not name:
        # Say so rather than dressing a guess as a decision.
        return f"language not detected — {stack.render()} → OTLP collector"
    return f"{name}: {stack.render()} → OTLP collector"
