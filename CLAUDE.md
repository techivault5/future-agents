# future-agents — Claude Code Configuration

## Token-Saving Rules (always active)

These rules apply to every response in this project. They exist to drastically cut token usage.

### Response style
- **Terse by default.** Answer in the fewest words that are correct and complete.
- No preamble: never open with "Great question!", "Sure!", "Of course!", "Certainly!", or any filler.
- No postamble: never close with "Let me know if you have questions", "Hope that helps!", or similar.
- Never restate what the user just said before answering.
- Never explain what you are about to do — just do it.
- Prefer code over prose for technical answers.
- One sentence of context max before a code block, zero if the code is self-evident.

### Repetition avoidance (memory-first)
- If a question was answered earlier in this session, refer back with "→ see above" and add only what changed. Do not repeat the full answer.
- If the user asks the same thing twice, say "Same as before: [one-line summary]" and stop.
- If you already showed a file or code block, don't show it again — reference it by filename/function name.

### Code comments
- No comments that restate what the code does (bad: `# increment counter`).
- Only comment WHY something non-obvious is done.
- No multi-line docstrings unless the user explicitly asks.

### Formatting
- Use bullet points and tables instead of paragraphs.
- Omit headers for short answers (< 5 lines).
- Abbreviate freely in inline comments (e.g., `init`, `cfg`, `msg`, `err`).

---

## Project layout (reference — do not re-explain)

```
future_agents/
  agents/          # BaseAgent subclasses
  core/            # EventBus, AgentRegistry, Orchestrator, BaseAgent
  definitions/     # JSON-based agent definitions + factory
  infrastructure/  # KnowledgeStore, MetricTracker, SyncEngine
  models/          # Pydantic models (knowledge, skill, feedback, etc.)
  patterns/        # Agentic patterns: PatternLibrary, ToolRegistry, ReActRunner, ReflectionRunner
  workers/         # BaseWorker, WorkerScheduler, + 5 worker types
  system.py        # AgentSystem — top-level entry point
scripts/workers/   # GitHub Actions entrypoints (no framework deps)
tests/             # pytest, asyncio_mode=auto
```

## Key facts (do not re-derive)
- Python 3.11+, Pydantic v2, ruff for lint/format, pytest-asyncio (auto mode)
- `MetricTracker._series` (not `_time_series`) — dict of `list[MetricPoint]`
- `KnowledgeStore._entries` — dict keyed by entry id
- Workers: `CodeImprovementWorker`, `PatternDiscoveryWorker`, `AgentGathererWorker`, `KnowledgeSynthesisWorker`, `AIDiscoveryWorker`
- `anthropic` is optional — import guards via `try/except ImportError`
- Claude model: `claude-opus-4-7` with `thinking: {type: "adaptive"}`
- Install AI extras: `pip install -e ".[ai]"`

## Commands
```bash
pytest --tb=short -q          # run tests
ruff check . && ruff format . # lint + format
pip install -e ".[dev]"       # dev deps
pip install -e ".[ai]"        # + anthropic SDK
```
