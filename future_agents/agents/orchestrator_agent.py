"""Smart Orchestrator Agent — routes any user request to the best IT role agent.

Architecture
------------
1. **Intent classification** — categorise the request (code_review, architecture, security, …)
2. **Domain extraction**     — detect tech domain (frontend, backend, devops, security, …)
3. **Stack detection**       — detect mentioned technologies (react, python, k8s, …)
4. **Seniority inference**   — estimate required expertise from question complexity
5. **Agent scoring**         — score every entry in the 10 K catalog and return top N
6. **Context building**      — load the winner's YAML and build a rich LLM-ready persona
7. **Guardrails enforcement**— inline checks: secrets, PII, escalation triggers, profile rules
8. **Conversation memory**   — rolling window of past turns for follow-up awareness

The orchestrator intentionally contains NO LLM calls.  It acts as an intelligent
pre-processing layer: it selects the right expert persona, builds the context /
system-prompt, and applies guardrails.  The actual answer is produced by whichever
LLM has this context (Claude in VSCode, the REST API caller, etc.).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).parent.parent.parent
_AGENTS_DIR = _REPO_ROOT / "agents"
_INDEX_FILE = _AGENTS_DIR / "agents_index.json"

# ── Intent + domain keyword maps ─────────────────────────────────────────────

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "code_review": ["review", "check", "audit", "analyse", "analyze", "lint", "quality", "clean", "smell", "refactor"],
    "architecture": [
        "design",
        "architect",
        "structure",
        "pattern",
        "diagram",
        "system design",
        "scalab",
        "modular",
        "microservice",
        "monolith",
    ],
    "security": [
        "security",
        "vulnerab",
        "auth",
        "permission",
        "hack",
        "injection",
        "xss",
        "csrf",
        "owasp",
        "pentest",
        "encrypt",
        "jwt",
        "oauth",
        "ssrf",
        "rce",
        "privilege",
    ],
    "debugging": [
        "bug",
        "error",
        "fix",
        "broken",
        "issue",
        "crash",
        "traceback",
        "exception",
        "fail",
        "wrong",
        "problem",
        "debug",
    ],
    "deployment": [
        "deploy",
        "release",
        "ship",
        "ci",
        "cd",
        "pipeline",
        "docker",
        "kubernetes",
        "k8s",
        "helm",
        "container",
        "infra",
        "terraform",
        "cloud",
        "aws",
        "gcp",
        "azure",
    ],
    "development": ["build", "create", "implement", "develop", "write", "code", "generate", "scaffold", "boilerplate"],
    "optimization": [
        "optim",
        "performance",
        "slow",
        "faster",
        "efficient",
        "profil",
        "memory",
        "cpu",
        "latency",
        "throughput",
        "cache",
    ],
    "testing": [
        "test",
        "unit",
        "integration",
        "e2e",
        "mock",
        "coverage",
        "fixture",
        "assert",
        "pytest",
        "jest",
        "spec",
    ],
    "documentation": ["document", "readme", "docs", "comment", "explain", "api doc", "swagger", "openapi", "runbook"],
    "data": [
        "data",
        "pipeline",
        "etl",
        "warehouse",
        "analytics",
        "query",
        "sql",
        "nosql",
        "migrate",
        "schema",
        "index",
    ],
    "ml_ai": [
        "machine learning",
        "ml",
        "model",
        "train",
        "inference",
        "neural",
        "nlp",
        "cv",
        "llm",
        "embedding",
        "fine-tun",
    ],
}

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    # Frontend: specific frameworks/tools only, NO generic 2-3-char words
    "frontend": [
        "react",
        "vue",
        "angular",
        "svelte",
        "nextjs",
        "nuxt",
        "html",
        "css",
        "sass",
        "webpack",
        "vite",
        "tailwind",
        "browser",
        "dom",
        "spa",
        "ssr",
        "accessibility",
        "a11y",
        "component",
        "storybook",
        "figma",
        "typescript frontend",
        "jamstack",
    ],
    # Backend: languages/frameworks — word-boundary enforced by _extract_domains for short ones
    "backend": [
        "django",
        "fastapi",
        "flask",
        "express",
        "spring",
        "rails",
        "laravel",
        "graphql",
        "grpc",
        "dotnet",
        "asp.net",
        "gin",
        "actix",
        "fiber",
        "python",
        "java",
        "golang",
        "node.js",
        "nodejs",
        "ruby",
        "php",
        "rest api",
        "microservice",
        "monolith",
    ],
    # DevOps: infra/pipeline tools — more specific terms
    "devops": [
        "docker",
        "kubernetes",
        "k8s",
        "helm",
        "terraform",
        "ansible",
        "jenkins",
        "github actions",
        "gitlab ci",
        "argocd",
        "monitoring",
        "prometheus",
        "grafana",
        "sre",
        "observability",
        "infrastructure",
        "eks",
        "aks",
        "gke",
        "ecs",
        "fargate",
        "circleci",
        "tekton",
        "gitops",
        "flux",
        "crossplane",
        "pulumi",
        "packer",
    ],
    # Security: more specific terms including "vulnerability", "injection"
    "security": [
        "owasp",
        "pentest",
        "sast",
        "dast",
        "cve",
        "zero-day",
        "firewall",
        "iam",
        "rbac",
        "mfa",
        "tls",
        "ssl",
        "certificate",
        "hsm",
        "soc2",
        "iso27001",
        "gdpr",
        "compliance",
        "vulnerability",
        "injection",
        "xss",
        "csrf",
        "ssrf",
        "sqli",
        "devsecops",
        "sonarqube",
        "snyk",
        "burp suite",
        "nmap",
        "metasploit",
        "appsec",
    ],
    # Data: databases and pipeline tools
    "data": [
        "sql",
        "postgres",
        "mysql",
        "mongodb",
        "redis",
        "elasticsearch",
        "kafka",
        "spark",
        "airflow",
        "dbt",
        "bigquery",
        "snowflake",
        "databricks",
        "pandas",
        "etl",
        "warehouse",
        "data lake",
        "redshift",
        "fivetran",
        "stitch",
        "duckdb",
        "clickhouse",
    ],
    # Mobile: platform-specific keywords
    "mobile": [
        "ios",
        "android",
        "swift",
        "kotlin",
        "react native",
        "flutter",
        "expo",
        "xctest",
        "espresso",
        "app store",
        "push notification",
        "xcode",
        "android studio",
        "swiftui",
        "jetpack compose",
    ],
    # ML: more specific — transformer (not transformers), huggingface, mlflow
    "ml": [
        "tensorflow",
        "pytorch",
        "keras",
        "sklearn",
        "huggingface",
        "hugging face",
        "transformer",
        "langchain",
        "mlflow",
        "mlops",
        "ray",
        "cuda",
        "gpu training",
        "fine-tune",
        "fine-tuning",
        "embedding",
        "vector database",
        "rag",
        "llm",
        "diffusion",
        "yolo",
        "bert",
        "gpt",
        "stable diffusion",
        "openai",
        "anthropic",
    ],
    # Cloud: provider-specific services
    "cloud": [
        "aws",
        "gcp",
        "azure",
        "lambda",
        "s3 bucket",
        "ec2",
        "cloudfront",
        "cloud run",
        "serverless",
        "cdn",
        "cloudflare",
        "route53",
        "azure devops",
        "google cloud",
        "digitalocean",
        "linode",
    ],
    # Management: non-technical PM/leadership domain
    "management": [
        "project manager",
        "product manager",
        "product owner",
        "scrum master",
        "agile coach",
        "business analyst",
        "it manager",
        "it director",
        "stakeholder",
        "sprint",
        "backlog",
        "roadmap planning",
        "change management",
        "risk management",
        "budget",
        "procurement",
    ],
}

# Domain → role keyword hints (what agent role substring to look for)
_DOMAIN_ROLE_MAP: dict[str, list[str]] = {
    "frontend": ["frontend"],
    "backend": ["backend", "full-stack", "fullstack"],
    "devops": ["devops", "platform-engineering", "site-reliability", "infrastructure", "cloud-engineering", "sre"],
    "security": ["security", "cybersecurity", "infosec", "appsec", "devsecops", "penetration"],
    # data-engineering listed first so pipeline questions rank above database-administration
    "data": ["data-engineering", "analytics", "data-architect", "data-science", "database", "data-analyst"],
    "mobile": ["mobile", "ios-development", "android-development"],
    "ml": ["machine-learning", "ml-engineering", "data-science", "ai-engineering", "mlops"],
    "cloud": ["cloud-engineering", "devops", "platform-engineering"],
    "management": ["project-management", "product-management", "it-management", "program-management", "scrum", "agile"],
}

# Intent → role keyword hints (secondary signal when domain is weak)
_INTENT_ROLE_HINTS: dict[str, list[str]] = {
    "ml_ai": ["machine-learning", "data-science", "ai-engineering", "mlops"],
    "security": ["security", "cybersecurity", "infosec", "appsec"],
    "deployment": ["devops", "platform-engineering", "sre", "cloud-engineering"],
    "data": ["data-engineering", "data-science", "analytics"],
    "testing": ["qa", "quality-assurance", "test-engineering"],
    "architecture": ["architect", "principal", "staff"],
}

# Keywords that strongly indicate a non-technical / management request
_NON_TECH_SIGNALS: list[str] = [
    "project manager",
    "product manager",
    "product owner",
    "scrum master",
    "agile coach",
    "business analyst",
    "it director",
    "it manager",
    "stakeholder",
    "sprint planning",
    "backlog grooming",
    "change management",
    "vendor management",
    "procurement",
    "it governance",
    "it strategy",
]

_STACK_TOKENS: set[str] = {
    "python",
    "javascript",
    "typescript",
    "java",
    "go",
    "rust",
    "ruby",
    "php",
    "c#",
    "dotnet",
    "swift",
    "kotlin",
    "scala",
    "elixir",
    "react",
    "vue",
    "angular",
    "svelte",
    "nextjs",
    "django",
    "fastapi",
    "flask",
    "express",
    "spring",
    "rails",
    "postgres",
    "mysql",
    "mongodb",
    "redis",
    "elasticsearch",
    "kafka",
    "docker",
    "kubernetes",
    "terraform",
    "ansible",
    "aws",
    "gcp",
    "azure",
    "firebase",
    "pytorch",
    "tensorflow",
    "sklearn",
    "langchain",
}

# Patterns that suggest a security-sensitive request requiring escalation
_ESCALATION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(password|passwd|credential|secret|token|api.?key)\b", re.I),
    re.compile(r"\b(payment|billing|credit.?card|pci.?dss|stripe|paypal)\b", re.I),
    re.compile(r"\b(pii|phi|hipaa|gdpr|personal.?data|ssn|social.?security)\b", re.I),
    re.compile(r"\b(production|prod)\s+(database|db|server|secret)\b", re.I),
    re.compile(r"\b(drop\s+table|truncate|delete\s+from)\b", re.I),
    re.compile(r"(?:password|passwd|api[_-]?key|secret|token)\s*[=:]\s*['\"].+['\"]", re.I),
]

# Patterns that detect embedded secrets in code snippets
_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:password|passwd|pwd)\s*[=:]\s*['\"](?!REPLACE_ME|your-|example|changeme)[^'\"]{6,}['\"]", re.I),
    re.compile(r"(?:api[_-]?key|apikey)\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", re.I),
    re.compile(r"(?:secret|token)\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", re.I),
    re.compile(r"sk-[A-Za-z0-9]{32,}", re.I),  # OpenAI style
    re.compile(r"ghp_[A-Za-z0-9]{36}", re.I),  # GitHub PAT
    re.compile(r"xox[bpoa]-[A-Za-z0-9\-]{16,}", re.I),  # Slack
    re.compile(r"AKIA[0-9A-Z]{16}", re.I),  # AWS access key
]


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class AgentMatch:
    agent_id: str
    agent_name: str
    role: str
    seniority: str
    agent_type: str
    match_score: float
    match_reasons: list[str]
    guardrails_profile: str = "standard"
    primary_stack: list[str] = field(default_factory=list)
    top_skills: list[str] = field(default_factory=list)


@dataclass
class GuardrailsResult:
    profile: str
    passed: bool
    secrets_found: list[str]
    escalation_required: bool
    escalation_reasons: list[str]
    warnings: list[str]
    recommendations: list[str]


@dataclass
class OrchestratorResponse:
    question: str
    intent: str
    domains: list[str]
    detected_stack: list[str]
    matched_agents: list[AgentMatch]
    primary_agent: Optional[AgentMatch]
    system_prompt: str  # Rich LLM-ready persona + instructions
    context_block: str  # Structured context the LLM should reference
    guardrails: GuardrailsResult
    confidence: float  # 0–1 match confidence
    multi_agent_suggested: bool
    suggested_workflow: Optional[str]
    timestamp: str


# ── Orchestrator ───────────────────────────────────────────────────────────────


class OrchestratorAgent:
    """Smart router that selects from 10,000 IT role agents and builds expert context.

    Parameters
    ----------
    agents_dir:   Path to the ``agents/`` directory (YAML catalog).
    index_file:   Path to ``agents_index.json`` (5-field fast index).
    max_history:  Rolling window of conversation turns to keep.
    """

    GUARDRAILS_PROFILES = {
        "strict": {"escalate_all_secrets": True, "block_prod_ops": True, "require_review": True},
        "standard": {"escalate_all_secrets": False, "block_prod_ops": False, "require_review": False},
        "relaxed": {"escalate_all_secrets": False, "block_prod_ops": False, "require_review": False},
        "architect": {"escalate_all_secrets": True, "block_prod_ops": True, "require_review": True},
    }

    def __init__(
        self,
        agents_dir: Path | str = _AGENTS_DIR,
        index_file: Path | str = _INDEX_FILE,
        max_history: int = 20,
    ) -> None:
        self._agents_dir = Path(agents_dir)
        self._index_file = Path(index_file)
        self._max_history = max_history
        self._index: list[dict] = []
        self._rich_cache: dict[str, dict] = {}  # agent_id → YAML data
        self._history: list[dict] = []  # conversation turns
        self._load_index()

    # ── Public API ─────────────────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        domain: Optional[str] = None,
        seniority: Optional[str] = None,
        top_k: int = 3,
        session_context: Optional[str] = None,
    ) -> OrchestratorResponse:
        """Main entry point: classify, route, build context, enforce guardrails."""

        # 1. Classify intent and domain
        intent = self._classify_intent(question)
        domains = self._extract_domains(question)
        if domain and domain not in domains:
            domains.insert(0, domain)
        stack = self._detect_stack(question)

        # 2. Check guardrails on the question itself (before doing anything)
        secrets = self._scan_secrets(question)
        escalations = self._check_escalation_triggers(question)

        # 3. Score agents
        agents = self._score_agents(question, domains, seniority, top_k, intent=intent)
        primary = agents[0] if agents else None

        # 4. Load primary agent YAML for rich context
        agent_def = self._load_yaml(primary.agent_id) if primary else None
        if agent_def and primary:
            primary.top_skills = (agent_def.get("key_skills") or [])[:8]
            raw_stack = agent_def.get("primary_stack") or agent_def.get("languages") or []
            # Guard: some YAML values are bare strings instead of lists
            if isinstance(raw_stack, str):
                raw_stack = [raw_stack]
            primary.primary_stack = [str(s) for s in raw_stack][:6]
            primary.guardrails_profile = agent_def.get("guardrails_profile", "standard")

        # 5. Build guardrails result
        profile = primary.guardrails_profile if primary else "standard"
        guardrails = GuardrailsResult(
            profile=profile,
            passed=not secrets and not escalations,
            secrets_found=secrets,
            escalation_required=bool(escalations),
            escalation_reasons=escalations,
            warnings=self._build_warnings(question, intent, profile),
            recommendations=self._build_recommendations(intent, stack, profile),
        )

        # 6. Build LLM context
        system_prompt = self._build_system_prompt(primary, agent_def, intent, domains, guardrails)
        context_block = self._build_context_block(
            question, primary, agent_def, intent, domains, stack, guardrails, session_context
        )

        # 7. Determine if multi-agent approach makes sense
        multi_agent = self._needs_multi_agent(question, intent, domains)
        workflow_suggestion = self._suggest_workflow(intent, domains) if multi_agent else None

        # 8. Store in history
        self._history.append(
            {
                "role": "user",
                "content": question,
                "intent": intent,
                "agent": primary.agent_id if primary else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        confidence = self._compute_confidence(agents, intent, domains)

        return OrchestratorResponse(
            question=question,
            intent=intent,
            domains=domains,
            detected_stack=stack,
            matched_agents=agents,
            primary_agent=primary,
            system_prompt=system_prompt,
            context_block=context_block,
            guardrails=guardrails,
            confidence=confidence,
            multi_agent_suggested=multi_agent,
            suggested_workflow=workflow_suggestion,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def find_agents(
        self,
        task: str,
        domain: Optional[str] = None,
        seniority: Optional[str] = None,
        agent_type: Optional[str] = None,
        limit: int = 10,
    ) -> list[AgentMatch]:
        """Return top N agents for a task, with scores and reasons."""
        domains = self._extract_domains(task)
        if domain:
            domains.insert(0, domain)
        intent = self._classify_intent(task)
        matches = self._score_agents(task, domains, seniority, limit, intent=intent)
        if agent_type:
            matches = [m for m in matches if m.agent_type == agent_type]
        return matches[:limit]

    def check_guardrails(self, content: str, profile: str = "standard") -> GuardrailsResult:
        """Scan content for secrets, escalation triggers, and policy issues."""
        secrets = self._scan_secrets(content)
        escalations = self._check_escalation_triggers(content)
        intent = self._classify_intent(content)
        stack = self._detect_stack(content)
        return GuardrailsResult(
            profile=profile,
            passed=not secrets and not escalations,
            secrets_found=secrets,
            escalation_required=bool(escalations),
            escalation_reasons=escalations,
            warnings=self._build_warnings(content, intent, profile),
            recommendations=self._build_recommendations(intent, stack, profile),
        )

    def clear_history(self) -> None:
        """Reset conversation memory."""
        self._history.clear()

    def history_summary(self) -> list[dict]:
        """Return recent conversation turns."""
        return list(self._history)

    def status(self) -> dict:
        """Return orchestrator status and catalog stats."""
        return {
            "catalog_size": len(self._index),
            "history_turns": len(self._history),
            "rich_cache_size": len(self._rich_cache),
            "agents_dir": str(self._agents_dir),
            "index_loaded": bool(self._index),
        }

    # ── Index loading ──────────────────────────────────────────────────────────

    def _load_index(self) -> None:
        if not self._index_file.exists():
            logger.warning("agents_index.json not found at %s", self._index_file)
            return
        try:
            with self._index_file.open() as f:
                self._index = json.load(f)
            logger.debug("Loaded %d agents from index", len(self._index))
        except Exception as exc:
            logger.error("Failed to load agent index: %s", exc)

    def _load_yaml(self, agent_id: str) -> Optional[dict]:
        if agent_id in self._rich_cache:
            return self._rich_cache[agent_id]
        for yaml_path in self._agents_dir.rglob(f"{agent_id}.yaml"):
            try:
                import yaml

                with yaml_path.open() as f:
                    data = yaml.safe_load(f)
                if data:
                    self._rich_cache[agent_id] = data
                    return data
            except Exception as exc:
                logger.debug("Failed to load %s: %s", yaml_path, exc)
        return None

    # ── Classification ─────────────────────────────────────────────────────────

    def _classify_intent(self, text: str) -> str:
        text_lower = text.lower()
        scores: dict[str, int] = {}
        for intent, keywords in _INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score:
                scores[intent] = score
        if not scores:
            return "development"
        return max(scores, key=lambda k: scores[k])

    def _extract_domains(self, text: str) -> list[str]:
        text_lower = text.lower()
        domain_scores: dict[str, int] = {}
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if len(kw) <= 3:
                    # Short keywords (sql, ios, go, k8s…): require word boundary
                    if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                        score += 1
                else:
                    # Longer keywords: substring match is fine
                    if kw in text_lower:
                        score += 1
            if score:
                domain_scores[domain] = score
        return sorted(domain_scores, key=lambda k: domain_scores[k], reverse=True)

    def _detect_stack(self, text: str) -> list[str]:
        text_lower = text.lower()
        return [tok for tok in _STACK_TOKENS if tok in text_lower]

    def _infer_seniority(self, text: str) -> Optional[str]:
        """Guess required seniority from question vocabulary."""
        text_lower = text.lower()
        senior_signals = sum(
            1
            for kw in [
                "design system",
                "trade-off",
                "distributed",
                "scalab",
                "enterprise",
                "architect",
                "lead",
                "strategy",
                "principle",
                "roadmap planning",
                "team lead",
                "tech lead",
                "principal",
                "staff engineer",
            ]
            if kw in text_lower
        )
        intern_signals = sum(
            1
            for kw in [
                "what is",
                "how do i",
                "how do you",
                "beginner",
                "tutorial",
                "getting started",
                "simple example",
                "hello world",
                "for beginners",
                "i'm new",
                "i am new",
                "first time",
            ]
            if kw in text_lower
        )
        if senior_signals >= 2:
            return "senior"
        if intern_signals >= 2:  # require 2+ signals to avoid false positives
            return "intern"
        return None

    def _is_non_technical(self, text: str) -> bool:
        """Return True if the request is clearly non-technical (PM, management, etc.)."""
        text_lower = text.lower()
        return any(sig in text_lower for sig in _NON_TECH_SIGNALS)

    # ── Agent scoring ──────────────────────────────────────────────────────────

    def _score_agents(
        self,
        query: str,
        domains: list[str],
        seniority: Optional[str],
        top_k: int,
        intent: str = "development",
    ) -> list[AgentMatch]:
        query_lower = query.lower()
        query_tokens = set(re.findall(r"\w+", query_lower))
        inferred_seniority = seniority or self._infer_seniority(query)
        is_non_tech = self._is_non_technical(query)

        scored: list[tuple[float, dict, list[str]]] = []

        for agent in self._index:
            score, reasons = self._score_one(
                agent,
                query_lower,
                query_tokens,
                domains,
                inferred_seniority,
                intent,
                is_non_tech,
            )
            if score > 0:
                scored.append((score, agent, reasons))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, agent, reasons in scored[:top_k]:
            results.append(
                AgentMatch(
                    agent_id=agent["id"],
                    agent_name=agent["name"],
                    role=agent["role"],
                    seniority=agent.get("seniority", "mid-level"),
                    agent_type=agent.get("type", "technical"),
                    match_score=round(min(score / 120.0, 1.0), 3),
                    match_reasons=reasons[:4],
                )
            )
        return results

    def _score_one(
        self,
        agent: dict,
        query_lower: str,
        query_tokens: set[str],
        domains: list[str],
        target_seniority: Optional[str],
        intent: str = "development",
        is_non_tech: bool = False,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        agent_role: str = agent.get("role", "")
        role_display = agent_role.replace("-", " ")
        role_tokens = set(role_display.split())
        agent_type: str = agent.get("type", "technical")

        # ── 1. Domain → role-hint match (highest weight, 45 pts primary) ────────
        for i, domain in enumerate(domains[:2]):
            role_hints = _DOMAIN_ROLE_MAP.get(domain, [domain])
            if any(hint in agent_role for hint in role_hints):
                weight = 45 - i * 15  # 45 for primary domain, 30 for secondary
                score += weight
                reasons.append(f"domain→role: {domain}")
                break

        # ── 2. Non-technical type match ──────────────────────────────────────────
        if is_non_tech:
            if agent_type == "non-technical":
                score += 40
                reasons.append("non-technical request")
            else:
                score -= 20  # strong penalty: don't give non-tech questions to coders

        # ── 3. Intent → role-hint match (secondary signal) ──────────────────────
        intent_hints = _INTENT_ROLE_HINTS.get(intent, [])
        if intent_hints and any(hint in agent_role for hint in intent_hints):
            score += 20
            reasons.append(f"intent→role: {intent}")

        # ── 4. Role token overlap with query ─────────────────────────────────────
        overlap = len(role_tokens & query_tokens)
        if overlap:
            score += overlap * 15
            reasons.append(f"query↔role tokens: {overlap}")

        # ── 5. Role slug appears verbatim in query ───────────────────────────────
        if agent_role in query_lower or role_display in query_lower:
            score += 25
            reasons.append(f"exact role in query: {agent_role}")

        # ── 6. Seniority match / mismatch ────────────────────────────────────────
        _SENIORITY_PREFERENCE = {
            # Higher = preferred when no explicit target is given
            "fellow": 9,
            "distinguished": 9,
            "principal": 8,
            "architect": 8,
            "senior": 8,
            "staff": 8,
            "lead": 6,
            "mid": 4,
            "junior": 2,
            "intern": 0,
        }
        agent_seniority = agent.get("seniority", "mid-level")
        if target_seniority:
            if agent_seniority == target_seniority:
                score += 20
                reasons.append(f"seniority match: {agent_seniority}")
            elif target_seniority == "intern" and agent_seniority in ("senior", "staff", "principal", "distinguished"):
                score -= 15  # over-qualified for a beginner question
            elif target_seniority == "senior" and agent_seniority == "intern":
                score -= 10
        else:
            # Prefer higher seniority when no explicit target
            score += _SENIORITY_PREFERENCE.get(agent_seniority, 3)

        # ── 7. Technical type bonus (for clearly technical questions) ────────────
        if not is_non_tech and agent_type == "technical":
            score += 4

        # ── 8. Agent name overlap ────────────────────────────────────────────────
        name_tokens = set(re.findall(r"\w+", agent.get("name", "").lower()))
        name_overlap = len(name_tokens & query_tokens)
        if name_overlap:
            score += name_overlap * 4

        return score, reasons

    # ── Context building ───────────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        agent: Optional[AgentMatch],
        agent_def: Optional[dict],
        intent: str,
        domains: list[str],
        guardrails: GuardrailsResult,
    ) -> str:
        if not agent:
            return (
                "You are a senior IT consultant with broad expertise. "
                "Answer the user's question with accuracy and practicality."
            )

        name = agent_def.get("name", agent.agent_name) if agent_def else agent.agent_name
        role = agent_def.get("role", agent.role) if agent_def else agent.role
        seniority = agent.seniority
        stack = agent.primary_stack or []
        skills = agent.top_skills or []
        profile = guardrails.profile

        persona_lines = [
            f"You are {name}, a {seniority}-level {role.replace('-', ' ')} expert.",
        ]

        if stack:
            persona_lines.append(f"Your primary technology stack: {', '.join(stack[:5])}.")

        if skills:
            persona_lines.append(f"Your core competencies: {', '.join(skills[:5])}.")

        if agent_def:
            tools = agent_def.get("tools") or []
            if tools:
                persona_lines.append(f"You are proficient with: {', '.join(str(t) for t in tools[:6])}.")

            languages = agent_def.get("languages") or []
            if languages and languages != stack:
                persona_lines.append(f"Languages you work in: {', '.join(str(lang) for lang in languages[:4])}.")

        # Guardrails instructions
        persona_lines.append("")
        persona_lines.append("## Guardrails & Standards")
        persona_lines.append(f"- Guardrails profile active: **{profile.upper()}**")
        persona_lines.append("- NEVER include secrets, credentials, or API keys in responses.")
        persona_lines.append("- Use environment variables for ALL external credentials.")
        persona_lines.append("- Use semver-compatible package version ranges (^, ~=).")

        if profile in ("strict", "architect"):
            persona_lines.append("- FLAG any auth, payment, PII, or PHI concerns immediately.")
            persona_lines.append("- Recommend security review for any sensitive changes.")
            persona_lines.append("- Require explicit approval before production operations.")

        if guardrails.escalation_required:
            persona_lines.append("")
            persona_lines.append("⚠️  ESCALATION REQUIRED: This request touches sensitive areas:")
            for reason in guardrails.escalation_reasons:
                persona_lines.append(f"   - {reason}")
            persona_lines.append("Acknowledge this and advise the user to involve appropriate stakeholders.")

        if guardrails.secrets_found:
            persona_lines.append("")
            persona_lines.append("🔴 SECRETS DETECTED in the user's question.")
            persona_lines.append("Immediately point this out and advise removing credentials before sharing.")

        # Intent-specific guidance
        intent_guidance = {
            "security": "Prioritise security best practices. Reference OWASP where relevant.",
            "architecture": "Think in systems: consider scalability, fault tolerance, and maintainability.",
            "code_review": "Be specific: cite line patterns, suggest concrete fixes, explain the 'why'.",
            "debugging": "Follow systematic diagnosis: reproduce, isolate, hypothesise, verify.",
            "deployment": "Consider rollback strategies, health checks, and zero-downtime approaches.",
            "optimization": "Profile before optimising. Quote measurements. Prefer readability unless proven bottleneck.",  # noqa: E501
            "testing": "Recommend arrange-act-assert. Aim for ≥80% coverage. Prefer unit over integration where possible.",  # noqa: E501
        }
        if intent in intent_guidance:
            persona_lines.append("")
            persona_lines.append(f"## Approach for {intent.replace('_', ' ').title()}")
            persona_lines.append(intent_guidance[intent])

        return "\n".join(persona_lines)

    def _build_context_block(
        self,
        question: str,
        agent: Optional[AgentMatch],
        agent_def: Optional[dict],
        intent: str,
        domains: list[str],
        stack: list[str],
        guardrails: GuardrailsResult,
        session_context: Optional[str],
    ) -> str:
        lines = ["## Orchestrator Context\n"]

        lines.append(f"**Intent classified:** `{intent}`")
        if domains:
            lines.append(f"**Domains detected:** {', '.join(domains[:3])}")
        if stack:
            lines.append(f"**Stack detected:** {', '.join(stack[:6])}")

        if agent:
            lines.append(
                f"\n**Routing to:** [{agent.agent_name}] `{agent.role}` "
                f"({agent.seniority}) — confidence {agent.match_score:.0%}"
            )
            if agent.match_reasons:
                lines.append(f"**Match reasons:** {', '.join(agent.match_reasons)}")
            lines.append(f"**Guardrails profile:** `{guardrails.profile}`")

        if guardrails.secrets_found:
            lines.append("\n🔴 **Secrets detected in input — do not echo these back:**")
            for s in guardrails.secrets_found:
                lines.append(f"  - {s}")

        if guardrails.escalation_required:
            lines.append("\n⚠️  **Human escalation required:**")
            for r in guardrails.escalation_reasons:
                lines.append(f"  - {r}")

        if guardrails.warnings:
            lines.append("\n**Guardrails warnings:**")
            for w in guardrails.warnings:
                lines.append(f"  - {w}")

        if guardrails.recommendations:
            lines.append("\n**Recommendations:**")
            for r in guardrails.recommendations:
                lines.append(f"  - {r}")

        if session_context:
            lines.append(f"\n**Session context:** {session_context}")

        if self._history:
            recent = self._history[-3:]
            lines.append("\n**Recent conversation turns:**")
            for turn in recent:
                lines.append(f"  - [{turn['intent']}] {turn['content'][:80]}…")

        return "\n".join(lines)

    # ── Guardrails helpers ────────────────────────────────────────────────────

    def _scan_secrets(self, text: str) -> list[str]:
        found = []
        for pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(text):
                snippet = match.group(0)
                # Redact the value part for safety
                redacted = re.sub(r'([=:]\s*[\'"])[^\'"]+', r"\1***REDACTED***", snippet)
                found.append(redacted)
        return found

    def _check_escalation_triggers(self, text: str) -> list[str]:
        triggers = []
        if re.search(r"\b(payment|billing|credit.?card|pci|stripe|paypal)\b", text, re.I):
            triggers.append("Payment / financial data — PCI-DSS compliance required")
        if re.search(r"\b(pii|phi|hipaa|personal.?data|patient|medical|health.?record)\b", text, re.I):
            triggers.append("PII/PHI data — privacy review required")
        if re.search(r"\b(prod(uction)?)\s+(database|db|secret|credential|key)\b", text, re.I):
            triggers.append("Production credentials mentioned — ops approval required")
        if re.search(r"\b(drop\s+table|truncate\s+table|delete\s+from)\b", text, re.I):
            triggers.append("Destructive database operation — explicit confirmation required")
        if re.search(r"\b(auth|authentication|authorisation|authorization)\b", text, re.I):
            triggers.append("Authentication/authorisation change — security review recommended")
        return triggers

    def _build_warnings(self, text: str, intent: str, profile: str) -> list[str]:
        warnings = []
        if re.search(r"verify\s*=\s*false", text, re.I):
            warnings.append("SSL verification disabled (verify=False) — never use in production")
        if re.search(r"shell\s*=\s*true", text, re.I):
            warnings.append("subprocess shell=True with potential user input — command injection risk")
        if re.search(r"\beval\s*\(", text, re.I):
            warnings.append("eval() detected — ensure input is fully trusted and sanitised")
        if re.search(r"pickle\.loads?\(", text, re.I):
            warnings.append("pickle.loads on untrusted data — RCE risk; use JSON instead")
        sql_concat = (
            re.search(r"cursor\.execute\s*\([^\)]*\+", text, re.I)
            or re.search(r"(execute|query|select|insert|update|delete).*\+\s*\w", text, re.I)
            or re.search(r"\+\s*(?:request|user|input|params|uid|id|name|email|var|data)\b", text, re.I)
        )
        if sql_concat:
            warnings.append("Possible SQL injection — use parameterised queries")
        if profile == "strict" and intent == "deployment":
            warnings.append("Strict profile: deployment changes require peer review before applying")
        return warnings

    def _build_recommendations(self, intent: str, stack: list[str], profile: str) -> list[str]:
        recs = []
        if intent == "security":
            recs.append("Run SAST (e.g. Bandit for Python, semgrep) before merging")
            recs.append("Review OWASP Top 10 checklist for your stack")
        if intent == "deployment" and ("docker" in stack or "kubernetes" in stack):
            recs.append("Add health-check endpoints and readiness/liveness probes")
            recs.append("Use multi-stage Docker builds to minimise image surface area")
        if intent == "testing":
            recs.append("Target ≥80% test coverage (pytest --cov, jest --coverage)")
        if "python" in stack:
            recs.append("Use pyproject.toml with semver ranges (~=) for dependencies")
            recs.append("Run `pip audit` to check for known vulnerabilities")
        if any(t in stack for t in ["node", "react", "vue", "angular"]):
            recs.append("Run `npm audit` before every release")
        return recs

    # ── Multi-agent helpers ────────────────────────────────────────────────────

    def _needs_multi_agent(self, text: str, intent: str, domains: list[str]) -> bool:
        """Return True if the task likely benefits from chaining multiple agents."""
        if len(domains) >= 3:
            return True
        multi_signals = [
            "end to end",
            "full stack",
            "from scratch",
            "complete project",
            "architecture and implementation",
            "design and build",
        ]
        text_lower = text.lower()
        return any(s in text_lower for s in multi_signals)

    def _suggest_workflow(self, intent: str, domains: list[str]) -> Optional[str]:
        if intent == "security":
            return "tpl-guardrails-pipeline"
        if intent in ("deployment", "devops"):
            return "tpl-http-enrich-agent"
        if "data" in domains:
            return "tpl-batch-loop"
        return "tpl-agent-search-notify"

    # ── Confidence scoring ─────────────────────────────────────────────────────

    def _compute_confidence(self, agents: list[AgentMatch], intent: str, domains: list[str]) -> float:
        if not agents:
            return 0.1
        top_score = agents[0].match_score
        # Boost if intent and domain were detected
        boost = 0.0
        if intent != "development":  # non-default intent → specific match
            boost += 0.1
        if domains:
            boost += 0.05 * min(len(domains), 3)
        return round(min(top_score + boost, 1.0), 3)
