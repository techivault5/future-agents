"""Tracking — every ask broken into items that can be worked, posted and measured.

Three things, in one place because they are one idea:

* **Breakdown** (`breakdown.py`) — the ask becomes an epic, an item per
  requirement, and a sub-item per task, each carrying who asked, what it
  delivers, where the code goes and what "done" means.
* **Issues** (`issues.py`) — those items rendered as a GitHub tracking issue and
  its sub-issues, bodies written for whoever picks them up cold.
* **Metrics** (`metrics.py`) — a number per item with the question it answers,
  across delivery, quality, reliability, product and cost.

`publisher.py` is the seam for posting: one method, no GitHub client, dry run by
default, so creating something real is always a deliberate act by the caller.
"""

from __future__ import annotations

from future_agents.sdd.models import (
    MetricKind,
    MetricSet,
    MetricSpec,
    WorkBreakdown,
    WorkItem,
    WorkItemKind,
    WorkItemStatus,
)
from future_agents.sdd.tracking.breakdown import WorkBreakdownBuilder
from future_agents.sdd.tracking.issues import IssueBuilder, IssuePayload
from future_agents.sdd.tracking.metrics import MetricPlanner, refresh_values
from future_agents.sdd.tracking.publisher import (
    DryRunPublisher,
    JsonlPublisher,
    Publisher,
    PublishReport,
    publish_breakdown,
)

__all__ = [
    "DryRunPublisher",
    "IssueBuilder",
    "IssuePayload",
    "JsonlPublisher",
    "MetricKind",
    "MetricPlanner",
    "MetricSet",
    "MetricSpec",
    "PublishReport",
    "Publisher",
    "WorkBreakdown",
    "WorkBreakdownBuilder",
    "WorkItem",
    "WorkItemKind",
    "WorkItemStatus",
    "publish_breakdown",
    "refresh_values",
]
