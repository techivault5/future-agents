"""Intake — any ticket, from any system, becomes one Objective.

    objective = objective_from_payload(github_webhook_body)
    run = pipeline.start(objective)

Text that arrives from outside is sanitised on the way in (see `sanitize`), and
every objective carries an `ExternalRef` so the same ticket never starts a second
run.
"""

from future_agents.sdd.intake.adapters import (
    ADAPTERS,
    GenericTicketAdapter,
    GitHubIssueAdapter,
    IntakeAdapter,
    JiraAdapter,
    LinearAdapter,
    SlackAdapter,
    TranscriptAdapter,
    detect_adapter,
    objective_from_payload,
)
from future_agents.sdd.intake.sanitize import INJECTION_PATTERNS, SanitizedText, sanitize

__all__ = [
    "ADAPTERS",
    "INJECTION_PATTERNS",
    "GenericTicketAdapter",
    "GitHubIssueAdapter",
    "IntakeAdapter",
    "JiraAdapter",
    "LinearAdapter",
    "SanitizedText",
    "SlackAdapter",
    "TranscriptAdapter",
    "detect_adapter",
    "objective_from_payload",
    "sanitize",
]
