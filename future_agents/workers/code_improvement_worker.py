"""Code Improvement Worker — analyses code quality and proposes improvements."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from future_agents.core.events import Event, EventBus
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.infrastructure.sync_engine import Improvement, ImprovementType, SyncEngine
from future_agents.models.knowledge import KnowledgeEntry
from future_agents.workers.base_worker import BaseWorker, WorkerResult

logger = logging.getLogger(__name__)


class CodeImprovementWorker(BaseWorker):
    """Scans code quality and surfaces improvement proposals.

    Each cycle:
    1. Runs ruff (already a project dependency) to find lint issues.
    2. Checks MetricTracker series for agents with declining scores.
    3. Records high-priority pending improvements in the KnowledgeStore.
    4. Emits a ``worker.code_improvement.cycle_complete`` event.
    """

    def __init__(
        self,
        sync_engine: SyncEngine,
        knowledge_store: KnowledgeStore,
        metrics: MetricTracker,
        event_bus: EventBus,
        source_root: Path | str = ".",
        interval_seconds: int = 300,
        **kwargs: Any,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds, **kwargs)
        self.sync_engine = sync_engine
        self.knowledge_store = knowledge_store
        self.metrics = metrics
        self.event_bus = event_bus
        self.source_root = Path(source_root)

    @property
    def worker_type(self) -> str:
        return "code_improvement"

    async def run(self) -> WorkerResult:
        findings: list[str] = []
        improvements_proposed = 0

        lint_issues = await self._run_linter()
        if lint_issues:
            findings.append(f"Linter found {len(lint_issues)} issues")
            improvements_proposed += self._propose_lint_improvements(lint_issues)

        pending_high = [i for i in self.sync_engine.improvements if i.status == "proposed" and i.priority >= 0.7]
        if pending_high:
            findings.append(f"{len(pending_high)} high-priority improvements awaiting review")
            self._record_pending_improvements(pending_high)

        regressions = self._detect_regressions()
        if regressions:
            findings.append(f"Performance regressions: {', '.join(regressions)}")
            improvements_proposed += len(regressions)

        await self.event_bus.emit(
            Event(
                type="worker.code_improvement.cycle_complete",
                source=self.worker_id,
                data={
                    "lint_issues": len(lint_issues),
                    "improvements_proposed": improvements_proposed,
                    "findings": findings,
                },
            )
        )
        self.metrics.increment("workers.code_improvement.runs")
        self.metrics.increment(
            "workers.code_improvement.improvements_proposed",
            float(improvements_proposed),
        )

        return WorkerResult(
            worker_id=self.worker_id,
            success=True,
            data={
                "findings": findings,
                "lint_issues": len(lint_issues),
                "improvements_proposed": improvements_proposed,
            },
        )

    # ── Private ───────────────────────────────────────────────────────────────

    async def _run_linter(self) -> list[dict]:
        target = self.source_root / "future_agents"
        if not target.exists():
            return []
        try:
            proc = await asyncio.create_subprocess_exec(
                "ruff",
                "check",
                str(target),
                "--output-format",
                "json",
                "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if stdout.strip():
                return json.loads(stdout)
        except (asyncio.TimeoutError, FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning("Linter unavailable: %s", exc)
        return []

    def _propose_lint_improvements(self, issues: list[dict]) -> int:
        by_file: dict[str, list[dict]] = {}
        for issue in issues:
            by_file.setdefault(issue.get("filename", "unknown"), []).append(issue)

        count = 0
        for filepath, file_issues in sorted(by_file.items(), key=lambda x: -len(x[1]))[:5]:
            rel = Path(filepath).name
            codes = sorted({i.get("code", "?") for i in file_issues})
            imp = Improvement(
                type=ImprovementType.PROCESS_OPTIMIZATION,
                title=f"Lint issues in {rel}",
                description=(
                    f"{len(file_issues)} issue(s) in {rel}: {', '.join(codes[:5])}. Run `ruff check --fix` to auto-fix."
                ),
                priority=0.35,
                evidence=[f"{i.get('code')}: {i.get('message')}" for i in file_issues[:3]],
            )
            self.sync_engine._improvements.append(imp)
            count += 1

        if by_file:
            self.knowledge_store.add(
                KnowledgeEntry(
                    title="Code Quality Snapshot",
                    domain="engineering",
                    content=(
                        f"Linter found {len(issues)} issues across {len(by_file)} files. "
                        f"Top files: {', '.join(list(by_file)[:3])}. "
                        f"Run `ruff check --fix future_agents/` to resolve most automatically."
                    ),
                    tags=["code-quality", "linting", "ruff"],
                    source_agent=self.worker_id,
                    confidence=0.95,
                )
            )
        return count

    def _detect_regressions(self) -> list[str]:
        regressions: list[str] = []
        for key, points in self.metrics._series.items():
            if "feedback_scores" not in key or len(points) < 5:
                continue
            recent = [p.value for p in points[-5:]]
            avg = sum(recent) / len(recent)
            if avg < 0.5:
                agent_label = key.split("agent=")[-1].rstrip("}")
                regressions.append(agent_label)
                self.sync_engine._improvements.append(
                    Improvement(
                        type=ImprovementType.CAPABILITY_GAP,
                        title=f"Performance regression: {agent_label}",
                        description=(
                            f"Agent {agent_label} scored {avg:.2f} avg over the last 5 "
                            f"executions — investigate capability gaps."
                        ),
                        target_agent=agent_label,
                        priority=0.75,
                        evidence=[f"recent_avg={avg:.2f}"],
                    )
                )
        return regressions

    def _record_pending_improvements(self, improvements: list[Improvement]) -> None:
        summary = "; ".join(i.title for i in improvements[:5])
        self.knowledge_store.add(
            KnowledgeEntry(
                title="High-Priority Improvements Pending",
                domain="system",
                content=f"These improvements require human review: {summary}",
                tags=["improvements", "review-needed", "high-priority"],
                source_agent=self.worker_id,
                confidence=1.0,
            )
        )
