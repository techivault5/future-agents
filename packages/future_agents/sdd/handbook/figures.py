"""The handbook's figures — four diagrams that carry the architecture.

Each function returns a `Diagram`, so the same figure renders into the PDF as
vector art and exports to SVG/PNG for slides and READMEs:

    python scripts/generate_handbook.py --diagrams docs/diagrams
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors

from future_agents.sdd.handbook.diagrams import (
    ACCENT,
    AMBER,
    BOX_ALT,
    BOX_WARN,
    GREEN,
    MUTED,
    RED,
    Diagram,
)

BAND_UNDERSTAND = colors.HexColor("#f2f4f7")
BAND_DESIGN = colors.HexColor("#eef3fb")
BAND_EXECUTE = colors.HexColor("#eef6ef")
BAND_VERIFY = colors.HexColor("#faf3ec")


def delivery_pipeline() -> Diagram:
    """The whole system: intent in, verified delivery out, lesson recorded."""
    figure = Diagram(172, 116)
    figure.band(8, 26, "1 · Understand", BAND_UNDERSTAND)
    figure.band(34, 26, "2 · Design", BAND_DESIGN)
    figure.band(60, 26, "3 · Execute", BAND_EXECUTE)
    figure.band(86, 26, "4 · Verify and learn", BAND_VERIFY)

    # ── Understand ────────────────────────────────────────────────────────────
    intake = figure.node(
        6, 15, 36, 15, "Intake", "ticket · meeting · chat · webhook", badge="1", accent=ACCENT
    )
    clarify = figure.node(
        52, 15, 36, 15, "Clarify", "score intent, fail closed", badge="2", accent=ACCENT
    )
    human = figure.node(
        98, 15, 32, 15, "Human", "answers or a meeting", badge="3", fill=BOX_WARN, accent=AMBER
    )
    spec = figure.node(137, 15, 32, 15, "Spec", "REQ ids + criteria", badge="4", accent=ACCENT)
    figure.connect(intake, clarify)
    figure.connect(clarify, human)
    figure.connect(human, clarify, from_side="bottom", to_side="bottom", detour=31.0, dashed=True)
    figure.connect(human, spec)

    # ── Design ────────────────────────────────────────────────────────────────
    knowledge = figure.node(
        6, 41, 36, 15, "Repo knowledge", "what exists · where it goes", accent=ACCENT
    )
    plan = figure.node(52, 41, 36, 15, "Plan", "components + placement", badge="5", accent=ACCENT)
    tasks = figure.node(98, 41, 32, 15, "Task DAG", "test before code", badge="6", accent=ACCENT)
    memory = figure.node(137, 41, 32, 15, "Memory hub", "past pitfalls", fill=BOX_ALT, accent=MUTED)
    figure.connect(spec, plan, from_side="bottom", to_side="top", detour=38.5, label="spec hash")
    figure.connect(knowledge, plan)
    figure.connect(plan, tasks)
    figure.connect(memory, plan, from_side="bottom", to_side="bottom", detour=57.0, dashed=True)

    # ── Execute ───────────────────────────────────────────────────────────────
    queue = figure.node(6, 67, 36, 15, "Queue + worker", "lease · retry · dead letter", badge="7")
    dispatch = figure.node(
        52, 67, 36, 15, "Dispatch", "agent + skill, explained", badge="8", accent=GREEN
    )
    guards = figure.node(
        98,
        67,
        32,
        15,
        "Guards",
        "sandbox · budget · breaker",
        badge="9",
        fill=BOX_WARN,
        accent=RED,
    )
    work = figure.node(
        137, 67, 32, 15, "Work", "files changed, commands run", badge="10", accent=GREEN
    )
    figure.connect(
        tasks, dispatch, from_side="bottom", to_side="top", detour=62.5, label="plan hash"
    )
    figure.connect(queue, dispatch)
    figure.connect(dispatch, guards)
    figure.connect(guards, work)

    # ── Verify and learn ──────────────────────────────────────────────────────
    qa = figure.node(6, 93, 36, 15, "QA", "evidence, not claims", badge="11", accent=GREEN)
    delivery = figure.node(
        52, 93, 36, 15, "Delivery", "accepted? assumptions?", badge="12", accent=GREEN
    )
    harvest = figure.node(98, 93, 32, 15, "Harvest", "one case, pitfalls first", badge="13")
    figure.node(
        137,
        93,
        32,
        15,
        "Constitution",
        "gates every arrow above",
        fill=BOX_ALT,
        accent=MUTED,
    )
    figure.connect(work, qa, from_side="bottom", to_side="top", detour=84.5)
    figure.connect(qa, delivery)
    figure.connect(delivery, harvest)
    figure.connect(harvest, memory, from_side="top", to_side="bottom", detour=88.5, dashed=True)

    figure.caption(
        6,
        113,
        "Solid: the flow — work carries evidence from step 10 into QA. Dashed: feedback — "
        "a human answering, a lesson constraining the next plan.",
    )
    return figure


def autonomy_loop() -> Diagram:
    """A ticket arrives and is worked without anyone watching."""
    figure = Diagram(172, 92)
    figure.band(8, 34, "Intake and assignment", BAND_UNDERSTAND)
    figure.band(42, 42, "Execution under guards", BAND_EXECUTE)

    trackers = figure.node(
        5, 16, 33, 17, "Trackers", "GitHub · Jira · Linear · Slack", badge="1", accent=ACCENT
    )
    adapter = figure.node(
        45, 16, 30, 17, "Adapter", "→ Objective + ExternalRef", badge="2", accent=ACCENT
    )
    sanitiser = figure.node(
        81,
        16,
        30,
        17,
        "Sanitiser",
        "text is data, not orders",
        badge="3",
        fill=BOX_WARN,
        accent=AMBER,
    )
    queue = figure.node(
        117, 16, 30, 17, "Queue", "one owner, lease, retry", badge="4", accent=ACCENT
    )
    dead = figure.node(
        152, 16, 19, 17, "Dead letter", "poison stops", fill=BOX_WARN, accent=RED, font_size=5.8
    )
    figure.connect(trackers, adapter)
    figure.connect(adapter, sanitiser)
    figure.connect(sanitiser, queue)
    figure.connect(queue, dead)

    worker = figure.node(
        5, 52, 33, 17, "TicketWorker", "claim · heartbeat · persist", badge="5", accent=ACCENT
    )
    pipeline = figure.node(
        45, 52, 30, 17, "Pipeline", "clarify → plan → tasks", badge="6", accent=ACCENT
    )
    dispatcher = figure.node(
        81, 52, 30, 17, "Dispatcher", "kind · domain · past success", badge="7", accent=GREEN
    )
    agents = figure.node(
        117,
        52,
        54,
        17,
        "Agents and skills",
        "shell · callable · MCP · simulated",
        badge="8",
        accent=GREEN,
    )
    figure.connect(queue, worker, from_side="bottom", to_side="top", detour=45.0, label="claim")
    figure.connect(worker, pipeline)
    figure.connect(pipeline, dispatcher)
    figure.connect(dispatcher, agents)

    guards = figure.node(
        45,
        74,
        66,
        12,
        "Guards — sandbox · budget · breaker · loop detector",
        fill=BOX_WARN,
        accent=RED,
        font_size=6.0,
    )
    evidence = figure.node(
        117, 74, 54, 12, "Evidence → QA (a claim is not proof)", accent=GREEN, font_size=6.0
    )
    figure.connect(agents, evidence, from_side="bottom", to_side="top", detour=71.5)
    figure.connect(dispatcher, guards, from_side="bottom", to_side="top", detour=71.5, dashed=True)
    figure.connect(
        worker,
        queue,
        from_side="left",
        to_side="left",
        detour=1.5,
        dashed=True,
    )
    figure.caption(
        3, 90, "Dashed on the left: a failed run goes back on the queue, not into the void."
    )
    return figure


def traceability_chain() -> Diagram:
    """Why coverage is computable here instead of asserted."""
    figure = Diagram(172, 62)
    figure.band(6, 50, "One requirement, end to end", BAND_DESIGN)

    requirement = figure.node(4, 16, 30, 14, "REQ-002", "the requirement", accent=ACCENT)
    criterion = figure.node(40, 16, 34, 14, "REQ-002-AC-001", "Given / When / Then", accent=ACCENT)
    test = figure.node(80, 12, 30, 11, "T-005 test", "written first", accent=GREEN, font_size=6.2)
    code = figure.node(80, 26, 30, 11, "T-006 code", "depends on T-005", font_size=6.2)
    proof = figure.node(
        116, 16, 26, 14, "Evidence", "exit 0, not simulated", fill=BOX_WARN, accent=AMBER
    )
    check = figure.node(147, 16, 24, 14, "QA check", "verified", accent=GREEN)

    figure.connect(requirement, criterion)
    figure.connect(criterion, test)
    figure.connect(criterion, code)
    figure.connect(test, proof)
    figure.connect(code, proof)
    figure.connect(proof, check)

    figure.caption(
        4,
        46,
        "coverage = verified MUST criteria ÷ MUST criteria — computed from ids, "
        "never from a worker's claim.",
        bold=True,
    )
    figure.caption(
        4,
        52,
        "A simulated implementation cannot verify a behaviour, however green the "
        "surrounding suite is.",
    )
    return figure


def multi_repo_program() -> Diagram:
    """One objective, several repositories, one question set for the human."""
    figure = Diagram(172, 84)
    figure.band(8, 30, "Route and order", BAND_DESIGN)
    figure.band(38, 40, "Run per repository", BAND_EXECUTE)

    objective = figure.node(
        5, 15, 34, 16, "Objective", "one sentence from a human", badge="1", accent=ACCENT
    )
    router = figure.node(
        47, 15, 34, 16, "Routing", "name · keywords · language", badge="2", accent=ACCENT
    )
    waves = figure.node(
        89, 15, 34, 16, "Dependency waves", "api before web", badge="3", accent=ACCENT
    )
    questions = figure.node(
        131,
        15,
        40,
        16,
        "Merged questions",
        "asked once, not once per repo",
        badge="4",
        fill=BOX_WARN,
        accent=AMBER,
    )
    figure.connect(objective, router)
    figure.connect(router, waves)
    figure.connect(waves, questions)

    api = figure.node(5, 48, 40, 16, "checkout-api (Go)", "go test ./...", badge="5", accent=GREEN)
    web = figure.node(53, 48, 40, 16, "web-app (TypeScript)", "npm test", badge="6", accent=GREEN)
    figure.node(
        101,
        48,
        40,
        16,
        "platform-infra (Terraform)",
        "not routed here",
        fill=BOX_ALT,
        accent=MUTED,
    )
    answer = figure.node(
        149,
        48,
        22,
        16,
        "One answer sheet",
        "unblocks all",
        fill=BOX_WARN,
        accent=AMBER,
        font_size=5.8,
    )
    figure.connect(waves, api, from_side="bottom", to_side="top", detour=42.0)
    figure.connect(api, web)
    figure.connect(questions, answer, from_side="bottom", to_side="top", detour=44.0)
    figure.connect(answer, web, from_side="bottom", to_side="bottom", detour=70.0, dashed=True)

    figure.caption(
        5,
        76,
        "Each repository plans against its own toolchain, structure and persona; "
        "the human answers once for the whole program.",
    )
    return figure


def deployment_topology() -> Diagram:
    """How the system runs: what is a process, what is state, what is external."""
    figure = Diagram(172, 122)

    figure.zone(2, 12, 34, 46, "External", stroke=MUTED)
    figure.zone(40, 12, 62, 46, "Control plane (stateless)", stroke=ACCENT)
    figure.zone(40, 62, 62, 52, "Worker pool — scales on queue depth", stroke=GREEN)
    figure.zone(106, 12, 64, 46, "Engines and tools", stroke=ACCENT)
    figure.zone(106, 62, 64, 52, "State (durable)", stroke=AMBER)

    # ── External ──────────────────────────────────────────────────────────────
    trackers = figure.node(
        5,
        20,
        28,
        14,
        "Trackers",
        "GitHub · Jira · Linear · Slack",
        badge="1",
        accent=MUTED,
        font_size=6.2,
    )
    humans = figure.node(
        5, 38, 28, 14, "People", "answers · meetings · review", accent=AMBER, font_size=6.2
    )

    # ── Control plane ─────────────────────────────────────────────────────────
    api = figure.node(44, 20, 26, 14, "API", "/api/sdd/*", badge="2", accent=ACCENT, font_size=6.2)
    intake = figure.node(
        74, 20, 24, 14, "Intake", "adapt + sanitise", badge="3", accent=ACCENT, font_size=6.2
    )
    queue = figure.node(
        59,
        40,
        39,
        14,
        "Work queue",
        "lease · retry · dead letter",
        badge="4",
        accent=ACCENT,
        font_size=6.2,
    )
    figure.connect(trackers, api, label="webhook")
    figure.connect(humans, api, from_side="right", to_side="left", detour=39.0)
    figure.connect(api, intake)
    figure.connect(intake, queue, from_side="bottom", to_side="top")

    # ── Worker pool ───────────────────────────────────────────────────────────
    worker = figure.node(
        44, 70, 26, 15, "Worker", "claim · heartbeat", badge="5", accent=GREEN, font_size=6.2
    )
    pipeline = figure.node(
        74, 70, 24, 15, "Pipeline", "clarify → deliver", badge="6", accent=GREEN, font_size=6.2
    )
    dispatch = figure.node(
        44,
        92,
        54,
        15,
        "Dispatcher + guards",
        "agent · skill · sandbox · budget · breaker",
        badge="7",
        fill=BOX_WARN,
        accent=RED,
        font_size=6.2,
    )
    figure.connect(queue, worker, from_side="bottom", to_side="top", detour=64.0, label="claim")
    figure.connect(worker, pipeline)
    figure.connect(pipeline, dispatch, from_side="bottom", to_side="top", detour=88.5)

    # ── Engines and tools ─────────────────────────────────────────────────────
    gateway = figure.node(
        110, 20, 26, 14, "MCP gateway", "tools, per host auth", accent=ACCENT, font_size=6.2
    )
    engines = figure.node(
        140,
        20,
        26,
        14,
        "Model engines",
        "opus · sonnet · haiku",
        badge="8",
        accent=ACCENT,
        font_size=6.2,
    )
    runners = figure.node(
        110,
        40,
        56,
        14,
        "Toolchain runners",
        "the repo's own test · lint · build commands",
        badge="9",
        accent=GREEN,
        font_size=6.2,
    )
    # The corridor at x≈103 is the gap between the worker pool and the state zone.
    figure.connect(pipeline, gateway, from_side="right", to_side="left", detour=102.5)
    figure.connect(dispatch, runners, from_side="right", to_side="left", detour=104.0)
    figure.connect(gateway, engines)

    # ── State ─────────────────────────────────────────────────────────────────
    repos = figure.node(
        110,
        70,
        26,
        15,
        "Repositories",
        "workspace per run",
        badge="10",
        accent=AMBER,
        font_size=6.2,
    )
    runs = figure.node(
        140, 70, 26, 15, "Run store", "resumable JSON", badge="11", accent=AMBER, font_size=6.2
    )
    figure.node(110, 92, 26, 15, "Memory cases", "markdown + index", accent=AMBER, font_size=6.2)
    figure.node(140, 92, 26, 15, "Audit log", "append-only", accent=AMBER, font_size=6.2)
    figure.connect(dispatch, repos)
    figure.connect(worker, runs, from_side="top", to_side="top", detour=60.0, dashed=True)
    figure.connect(runners, repos, from_side="bottom", to_side="top", detour=57.5, dashed=True)

    figure.caption(
        3,
        118,
        "Stateless control plane and workers; everything durable is on the right. Scale workers "
        "on queue depth — the lease is what makes that safe.",
    )
    return figure


FIGURES = {
    "delivery-pipeline": delivery_pipeline,
    "deployment-topology": deployment_topology,
    "autonomy-loop": autonomy_loop,
    "traceability-chain": traceability_chain,
    "multi-repo-program": multi_repo_program,
}


def export_all(directory: str | Path = "docs/diagrams") -> list[Path]:
    """Write every figure as SVG (always) and PNG (when a raster backend exists)."""
    target = Path(directory)
    written: list[Path] = []
    for name, build in FIGURES.items():
        figure = build()
        written.append(figure.save_svg(target / f"{name}.svg"))
        png = figure.save_png(target / f"{name}.png")
        if png is not None:
            written.append(png)
    return written
