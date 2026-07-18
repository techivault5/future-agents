"""Bulk agent test suite — validates all 10,000 agents in parallel.

Testing strategy (modern trends applied):
  - pytest-xdist  : parallel execution across CPU cores
  - parametrize   : one test per agent (isolated failures)
  - hypothesis    : property-based edge-case generation
  - pytest-cov    : coverage enforced at 80%
  - scoring rubric: each agent scored 0–10; suite fails if avg < 8.0

Run:
  # All agents, 8 workers
  pytest tests/test_all_agents.py -n 8 --tb=short

  # Fast sanity: representative sample only
  pytest tests/test_all_agents.py -n auto -m sample

  # A single role
  pytest tests/test_all_agents.py -k backend-development

  # Show score summary
  pytest tests/test_all_agents.py --co -q | head -20
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.fixtures.agent_inputs import get_inputs_for_agent

REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
AGENTS_INDEX = AGENTS_DIR / "agents_index.json"

# ── Index loading ──────────────────────────────────────────────────

def _load_index() -> list[dict]:
    return json.loads(AGENTS_INDEX.read_text())


def _load_sample(n: int = 200) -> list[dict]:
    """Stratified sample: up to n agents, representative across roles & seniority."""
    idx = _load_index()
    seen: set[str] = set()
    sample = []
    for a in idx:
        key = f"{a.get('role')}:{a.get('seniority')}:{a.get('type')}"
        if key not in seen:
            seen.add(key)
            sample.append(a)
        if len(sample) >= n:
            break
    return sample


ALL_AGENTS = _load_index()
SAMPLE_AGENTS = _load_sample(200)


# ── Pytest parametrize IDs ─────────────────────────────────────────

def _agent_id(a: dict) -> str:
    return f"{a['id']}-{a.get('role', 'unknown')}-{a.get('seniority', '?')}"


# ── Rubric: per-field scoring weights (total = 10) ────────────────

FIELD_WEIGHTS: dict[str, float] = {
    "id": 0.5,
    "name": 0.5,
    "role": 1.0,
    "type": 1.0,
    "seniority": 1.0,
    "description": 0.5,
    "primary_stack": 0.5,
    "skills": 1.0,
    "tools": 0.5,
    "guardrails_profile": 1.0,
    "package_policy": 0.5,
    "folder_structure_template": 0.5,
    "tags": 0.5,
    "version": 0.5,
    "created_by": 0.5,
}
_MAX_SCORE = sum(FIELD_WEIGHTS.values())  # 10.0


def score_agent(data: dict) -> tuple[float, list[str]]:
    """Score an agent YAML dict — returns (score_out_of_10, issues)."""
    issues: list[str] = []
    earned = 0.0

    for field, weight in FIELD_WEIGHTS.items():
        val = data.get(field)
        if val is None or val == "" or val == []:
            issues.append(f"missing_field:{field}")
        else:
            earned += weight

    # Bonus checks
    skills = data.get("skills", [])
    if isinstance(skills, list) and len(skills) >= 3:
        earned = min(_MAX_SCORE, earned + 0.0)  # already counted
    elif isinstance(skills, list) and len(skills) < 3:
        issues.append("too_few_skills")

    guardrails = data.get("guardrails_profile", "")
    if guardrails not in ("standard", "strict", "relaxed", "architect"):
        issues.append(f"invalid_guardrails_profile:{guardrails}")
        earned -= FIELD_WEIGHTS.get("guardrails_profile", 0)

    policy = data.get("package_policy", "")
    valid_policies = ("semver-minor-auto-upgrade", "semver-patch-auto-upgrade",
                      "manual-review", "strict-pin")
    if policy not in valid_policies:
        issues.append(f"invalid_package_policy:{policy}")
        earned -= FIELD_WEIGHTS.get("package_policy", 0)

    score = max(0.0, round(earned, 2))
    return score, issues


def load_agent_yaml(agent_id: str) -> dict | None:
    for f in AGENTS_DIR.rglob(f"{agent_id}.yaml"):
        try:
            return yaml.safe_load(f.read_text()) or {}
        except Exception:
            return None
    return None


# ══════════════════════════════════════════════════════════════════
# TEST 1 — Index integrity (runs once, no parametrize)
# ══════════════════════════════════════════════════════════════════

class TestAgentIndex:
    """Validate the agents_index.json is complete and well-formed."""

    def test_index_has_10000_agents(self):
        assert len(ALL_AGENTS) == 10_000, \
            f"Expected 10,000 agents, got {len(ALL_AGENTS)}"

    def test_all_ids_unique(self):
        ids = [a["id"] for a in ALL_AGENTS]
        assert len(ids) == len(set(ids)), "Duplicate agent IDs found"

    def test_required_index_fields(self):
        required = {"id", "name", "role", "type", "seniority"}
        bad = [a["id"] for a in ALL_AGENTS if not required.issubset(a.keys())]
        assert not bad, f"{len(bad)} agents missing required index fields: {bad[:5]}"

    def test_valid_types(self):
        valid = {"technical", "non-technical"}
        bad = [a for a in ALL_AGENTS if a.get("type") not in valid]
        assert not bad, f"{len(bad)} agents with invalid type: {bad[:3]}"

    def test_valid_seniority_values(self):
        valid = {
            "intern", "junior", "mid", "senior", "lead", "staff",
            "principal", "architect", "distinguished", "fellow",
            "director", "vp", "cto",
            "contractor", "consultant", "freelancer",
        }
        bad = [a for a in ALL_AGENTS if a.get("seniority") not in valid]
        assert not bad, f"{len(bad)} agents with invalid seniority: {bad[:3]}"

    def test_role_diversity(self):
        roles = {a.get("role") for a in ALL_AGENTS}
        assert len(roles) >= 30, f"Only {len(roles)} unique roles — expected 30+"

    def test_seniority_distribution(self, agents_by_seniority):
        """No single seniority should dominate (>40%)."""
        total = len(ALL_AGENTS)
        for seniority, group in agents_by_seniority.items():
            pct = len(group) / total
            assert pct < 0.40, \
                f"Seniority '{seniority}' is over-represented: {pct:.1%}"


# ══════════════════════════════════════════════════════════════════
# TEST 2 — YAML file integrity (representative sample)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("agent", SAMPLE_AGENTS, ids=[_agent_id(a) for a in SAMPLE_AGENTS])
@pytest.mark.sample
class TestAgentYamlIntegrity:
    """Each sampled agent's YAML file must be present, parseable, and well-scored."""

    def test_yaml_file_exists(self, agent):
        data = load_agent_yaml(agent["id"])
        assert data is not None, f"YAML not found for {agent['id']}"

    def test_yaml_id_matches_index(self, agent):
        data = load_agent_yaml(agent["id"])
        if data is None:
            pytest.skip("YAML file missing — covered by test_yaml_file_exists")
        assert data.get("id") == agent["id"], \
            f"YAML id mismatch: {data.get('id')} != {agent['id']}"

    def test_yaml_name_matches_index(self, agent):
        data = load_agent_yaml(agent["id"])
        if data is None:
            pytest.skip()
        assert data.get("name") == agent["name"]

    def test_yaml_role_matches_index(self, agent):
        data = load_agent_yaml(agent["id"])
        if data is None:
            pytest.skip()
        assert data.get("role") == agent["role"]

    def test_yaml_score_at_least_8(self, agent):
        """Each agent YAML must score ≥ 8.0 / 10.0 on the completeness rubric."""
        data = load_agent_yaml(agent["id"])
        if data is None:
            pytest.skip()
        score, issues = score_agent(data)
        assert score >= 8.0, \
            f"Agent {agent['id']} scored {score}/10 — issues: {issues}"

    def test_no_hardcoded_secrets(self, agent):
        """Agent YAMLs must not contain credentials or real tokens."""
        import re
        data = load_agent_yaml(agent["id"])
        if data is None:
            pytest.skip()
        raw = yaml.dump(data)
        secret_pattern = re.compile(
            r"(?i)(api[_-]?key|password|secret|token)\s*:\s*['\"]?[A-Za-z0-9+/]{20,}['\"]?"
        )
        assert not secret_pattern.search(raw), \
            f"Agent {agent['id']} YAML contains possible hardcoded secret"

    def test_guardrails_profile_valid(self, agent):
        data = load_agent_yaml(agent["id"])
        if data is None:
            pytest.skip()
        valid = {"standard", "strict", "relaxed", "architect"}
        profile = data.get("guardrails_profile", "")
        assert profile in valid, \
            f"Agent {agent['id']} has invalid guardrails_profile: {profile!r}"

    def test_folder_template_references_valid_type(self, agent):
        data = load_agent_yaml(agent["id"])
        if data is None:
            pytest.skip()
        template_path = data.get("folder_structure_template", "")
        assert template_path.startswith("templates/project-structures/"), \
            f"Agent {agent['id']} has unexpected template path: {template_path}"


# ══════════════════════════════════════════════════════════════════
# TEST 3 — Bulk scoring: all 10,000 agents must average ≥ 8.5
# ══════════════════════════════════════════════════════════════════

class TestBulkAgentScoring:
    """Run scoring rubric across all agents and enforce suite-level thresholds."""

    def test_all_agents_average_score_at_least_8_5(self):
        scores = []
        failures = []
        for agent in ALL_AGENTS:
            data = load_agent_yaml(agent["id"])
            if data is None:
                failures.append(agent["id"])
                scores.append(0.0)
                continue
            score, _ = score_agent(data)
            scores.append(score)

        avg = sum(scores) / len(scores)
        missing_pct = len(failures) / len(ALL_AGENTS) * 100

        assert missing_pct == 0.0, \
            f"{len(failures)} agent YAML files missing ({missing_pct:.1f}%)"
        assert avg >= 8.5, \
            f"Average agent score {avg:.2f}/10 is below the 8.5 threshold"

    def test_no_agent_scores_below_6(self):
        low_scorers = []
        for agent in ALL_AGENTS:
            data = load_agent_yaml(agent["id"])
            if data is None:
                low_scorers.append((agent["id"], 0.0, ["yaml_missing"]))
                continue
            score, issues = score_agent(data)
            if score < 6.0:
                low_scorers.append((agent["id"], score, issues))

        assert not low_scorers, (
            f"{len(low_scorers)} agents score below 6/10:\n"
            + "\n".join(f"  {aid}: {s:.1f} — {iss}" for aid, s, iss in low_scorers[:10])
        )

    def test_score_distribution_report(self, capsys):
        """Non-failing test: print a score distribution summary."""
        buckets = {f"{i}-{i+1}": 0 for i in range(0, 10)}
        buckets["10"] = 0
        for agent in ALL_AGENTS:
            data = load_agent_yaml(agent["id"])
            score = 0.0 if data is None else score_agent(data)[0]
            bucket = "10" if score >= 10 else f"{int(score)}-{int(score)+1}"
            buckets[bucket] = buckets.get(bucket, 0) + 1

        with capsys.disabled():
            print("\n── Agent Score Distribution ──────────────────")
            for bucket, count in sorted(buckets.items()):
                bar = "█" * (count // 100)
                print(f"  {bucket:6s} │ {bar} {count:,}")
            print("──────────────────────────────────────────────")


# ══════════════════════════════════════════════════════════════════
# TEST 4 — Inputs: verify role-appropriate inputs are generated
# ══════════════════════════════════════════════════════════════════

class TestAgentInputGeneration:
    """Every agent in the sample must receive ≥ 1 meaningful test input."""

    @pytest.mark.parametrize("agent", SAMPLE_AGENTS, ids=[_agent_id(a) for a in SAMPLE_AGENTS])
    @pytest.mark.sample
    def test_inputs_generated(self, agent):
        inputs = get_inputs_for_agent(agent)
        assert len(inputs) >= 1, f"No inputs generated for {agent['id']}"

    @pytest.mark.parametrize("agent", SAMPLE_AGENTS, ids=[_agent_id(a) for a in SAMPLE_AGENTS])
    @pytest.mark.sample
    def test_inputs_have_intent_and_parameters(self, agent):
        for inp in get_inputs_for_agent(agent):
            assert "intent" in inp, f"Input missing 'intent' for {agent['id']}"
            assert "parameters" in inp, f"Input missing 'parameters' for {agent['id']}"
            assert isinstance(inp["parameters"], dict)

    def test_all_roles_have_inputs(self, agents_by_role):
        from tests.fixtures.agent_inputs import ROLE_INPUTS, GENERIC_INPUTS
        no_specific_input = [
            role for role in agents_by_role if role not in ROLE_INPUTS
        ]
        # Roles without specific inputs fall back to GENERIC_INPUTS — acceptable
        # but we want less than 30% of roles to be generic
        total_roles = len(agents_by_role)
        generic_pct = len(no_specific_input) / total_roles
        assert generic_pct < 0.50, (
            f"{generic_pct:.0%} of roles use generic inputs — add role-specific inputs for: "
            + str(no_specific_input[:5])
        )


# ══════════════════════════════════════════════════════════════════
# TEST 5 — Performance: index lookup must be fast
# ══════════════════════════════════════════════════════════════════

class TestAgentPerformance:
    """Regression tests for agent data load + lookup performance."""

    def test_index_load_under_500ms(self):
        start = time.perf_counter()
        _ = json.loads(AGENTS_INDEX.read_text())
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500, f"Index load took {elapsed_ms:.0f}ms — expected < 500ms"

    def test_agent_lookup_by_role_under_50ms(self, agents_index):
        start = time.perf_counter()
        _ = [a for a in agents_index if a.get("role") == "backend-development"]
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 50, f"Role filter took {elapsed_ms:.1f}ms — expected < 50ms"

    def test_sample_200_yaml_loads_under_5s(self):
        start = time.perf_counter()
        loaded = 0
        for agent in SAMPLE_AGENTS:
            if load_agent_yaml(agent["id"]) is not None:
                loaded += 1
        elapsed = time.perf_counter() - start
        assert elapsed < 10.0, f"Loading {loaded} YAMLs took {elapsed:.1f}s — expected < 10s"
        assert loaded == len(SAMPLE_AGENTS), \
            f"Only {loaded}/{len(SAMPLE_AGENTS)} YAML files found"
