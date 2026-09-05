"""Demo — spec-driven delivery, including the meeting escalation.

Run with: python -m examples.demo_spec_kit
"""

import tempfile

from future_agents.sdd import (
    DeliveryPipeline,
    IntakeSource,
    MemoryHub,
    Objective,
    SpecKitConfig,
)


def show(state) -> None:
    print(f"  stage: {state.stage.value}")
    if state.clarification:
        c = state.clarification
        print(f"  intent: {c.outcome.value} (confidence {c.confidence})")
        for question in state.pending_questions():
            print(f"    {'!' if question.blocking else '·'} {question.text}")
        for assumption in c.assumptions:
            print(f"    assumed [{assumption.risk}] {assumption.statement}")
    if state.spec:
        for requirement in state.spec.requirements:
            print(f"    {requirement.id} [{requirement.priority.value}] {requirement.statement}")
    if state.qa:
        for line in state.qa.summary_lines():
            print(f"    {line}")
    if state.delivery:
        print(f"  delivery: {'ACCEPTED' if state.delivery.accepted else 'NOT ACCEPTED'}")


def main() -> None:
    config = SpecKitConfig.load()
    config.memory_hub.case_studies_path = tempfile.mkdtemp()
    pipeline = DeliveryPipeline(config, memory=MemoryHub(config.memory_hub))

    print("=== 1. A well-formed meeting objective runs straight through ===")
    clear = Objective(
        statement=(
            "Sales must get a weekly churn report so that account managers can "
            "call at-risk customers"
        ),
        context="Ops review 2026-09-01.",
        source=IntakeSource.MEETING,
        submitted_by="dana",
        raw_inputs=[
            "Dana: the report pulls from Snowflake every Monday 09:00\n"
            "Ravi: flag any account whose usage dropped 20% or more\n"
            "Priya: billing integration is out of scope for this phase"
        ],
        constraints=["no new production env vars"],
        deadline="2026-10-01",
    )
    show(pipeline.start(clear))

    print("\n=== 2. A vague objective stops and asks for a meeting ===")
    vague = Objective(statement="Make the dashboard faster", submitted_by="sam")
    state = pipeline.start(vague)
    show(state)

    print("\n=== 3. The meeting closes the unknowns and the run continues ===")
    answers = {
        q.id: "p95 under 800ms, from a 3.2s baseline, measured in Grafana"
        for q in state.pending_questions()
    }
    state = pipeline.hold_meeting(state, "Ops owns sign-off. Baseline 3.2s.", answers)
    show(state)

    print("\n=== 4. The run is now a case the next plan will read ===")
    report = pipeline.memory.retrieve("make the dashboard faster")
    for match in report.matches:
        print(f"  {match.case.id} [{match.case.outcome}] {match.case.title}")
        for pitfall in match.case.pitfalls:
            print(f"    - {pitfall}")


if __name__ == "__main__":
    main()
