"""Role-appropriate test inputs for every agent category.

Each role maps to a list of (intent, parameters) tuples that represent
realistic tasks a developer would send to that agent type.
Inputs are used in bulk agent testing (test_all_agents.py).
"""

from __future__ import annotations

from typing import Any

# ── Input catalog ─────────────────────────────────────────────────
# Keyed by role name (matches agents_index.json "role" field).
# Fallback: GENERIC_INPUTS used when role has no specific entry.

ROLE_INPUTS: dict[str, list[dict[str, Any]]] = {

    # ── Technical Roles ───────────────────────────────────────────

    "backend-development": [
        {"intent": "capability.register", "parameters": {
            "name": "REST API Design", "domain": "engineering",
            "level": "intermediate", "tags": ["python", "fastapi"]}},
        {"intent": "capability.assess", "parameters": {
            "capability_id": "cap-001", "criteria": ["performance", "scalability"]}},
    ],

    "frontend-development": [
        {"intent": "capability.register", "parameters": {
            "name": "React Component Development", "domain": "engineering",
            "level": "advanced", "tags": ["react", "typescript"]}},
        {"intent": "skill.map", "parameters": {
            "title": "Senior Frontend Engineer", "skills": ["React", "TypeScript", "CSS"]}},
    ],

    "fullstack-development": [
        {"intent": "capability.register", "parameters": {
            "name": "Full Stack Feature Delivery", "domain": "engineering",
            "level": "advanced", "tags": ["react", "node", "postgres"]}},
    ],

    "devops-engineering": [
        {"intent": "capability.register", "parameters": {
            "name": "CI/CD Pipeline Design", "domain": "infrastructure",
            "level": "expert", "tags": ["github-actions", "kubernetes"]}},
        {"intent": "process.define", "parameters": {
            "name": "Deployment Pipeline", "steps": ["build", "test", "deploy"]}},
    ],

    "cloud-architecture": [
        {"intent": "capability.register", "parameters": {
            "name": "AWS Solution Architecture", "domain": "cloud",
            "level": "expert", "tags": ["aws", "terraform"]}},
        {"intent": "policy.define", "parameters": {
            "name": "Cloud Cost Policy", "rules": [
                {"condition": "cost exceeds budget", "action": "alert team", "severity": "high"}
            ]}},
    ],

    "data-engineering": [
        {"intent": "capability.register", "parameters": {
            "name": "Data Pipeline Development", "domain": "data",
            "level": "advanced", "tags": ["spark", "airflow", "dbt"]}},
        {"intent": "knowledge.store", "parameters": {
            "topic": "Data Lake Architecture", "content": "S3 + Delta Lake pattern",
            "tags": ["data-lake", "s3"]}},
    ],

    "data-science": [
        {"intent": "capability.register", "parameters": {
            "name": "ML Model Development", "domain": "data-science",
            "level": "expert", "tags": ["python", "sklearn", "pytorch"]}},
        {"intent": "skill.map", "parameters": {
            "title": "Data Scientist", "skills": ["Python", "ML", "Statistics"]}},
    ],

    "ai-llm-engineering": [
        {"intent": "capability.register", "parameters": {
            "name": "LLM Integration & Prompt Engineering", "domain": "ai",
            "level": "expert", "tags": ["openai", "langchain", "rag"]}},
        {"intent": "knowledge.store", "parameters": {
            "topic": "RAG Architecture", "content": "Retrieval-Augmented Generation pattern",
            "tags": ["ai", "llm", "rag"]}},
    ],

    "database-administration": [
        {"intent": "capability.register", "parameters": {
            "name": "SQL Server Administration", "domain": "database",
            "level": "expert", "tags": ["mssql", "performance-tuning"]}},
        {"intent": "policy.define", "parameters": {
            "name": "Database Backup Policy", "rules": [
                {"condition": "daily", "action": "full backup", "severity": "critical"}
            ]}},
    ],

    "appsec-engineering": [
        {"intent": "capability.register", "parameters": {
            "name": "Application Security Review", "domain": "security",
            "level": "expert", "tags": ["owasp", "pentesting", "sast"]}},
        {"intent": "policy.define", "parameters": {
            "name": "Secrets Management Policy", "rules": [
                {"condition": "secret in code", "action": "block deploy", "severity": "critical"}
            ]}},
    ],

    "cloud-security": [
        {"intent": "capability.register", "parameters": {
            "name": "Cloud Security Posture Management", "domain": "security",
            "level": "expert", "tags": ["cspm", "aws-security", "iam"]}},
    ],

    "embedded-systems": [
        {"intent": "capability.register", "parameters": {
            "name": "Firmware Development", "domain": "embedded",
            "level": "advanced", "tags": ["c", "rtos", "arm"]}},
    ],

    "mobile-development": [
        {"intent": "capability.register", "parameters": {
            "name": "iOS/Android App Development", "domain": "mobile",
            "level": "advanced", "tags": ["swift", "kotlin", "react-native"]}},
    ],

    "blockchain-development": [
        {"intent": "capability.register", "parameters": {
            "name": "Smart Contract Development", "domain": "blockchain",
            "level": "expert", "tags": ["solidity", "ethereum", "web3"]}},
    ],

    "ar-vr-development": [
        {"intent": "capability.register", "parameters": {
            "name": "XR Application Development", "domain": "xr",
            "level": "advanced", "tags": ["unity", "unreal", "openxr"]}},
    ],

    "developer-relations": [
        {"intent": "knowledge.store", "parameters": {
            "topic": "API Developer Experience", "content": "Docs, SDKs, tutorials",
            "tags": ["devrel", "api", "docs"]}},
    ],

    # ── Non-Technical Roles ────────────────────────────────────────

    "business-analysis": [
        {"intent": "capability.register", "parameters": {
            "name": "Requirements Elicitation", "domain": "business-analysis",
            "level": "advanced", "tags": ["bpmn", "user-stories"]}},
        {"intent": "process.define", "parameters": {
            "name": "Requirements Gathering", "steps": [
                "stakeholder-interviews", "gap-analysis", "documentation"]}},
    ],

    "it-operations-management": [
        {"intent": "process.define", "parameters": {
            "name": "Incident Response", "steps": [
                "detect", "triage", "resolve", "post-mortem"]}},
        {"intent": "policy.define", "parameters": {
            "name": "SLA Policy", "rules": [
                {"condition": "P1 incident", "action": "respond in 15 min", "severity": "critical"}
            ]}},
    ],

    "it-governance": [
        {"intent": "policy.define", "parameters": {
            "name": "IT Governance Framework", "rules": [
                {"condition": "major change", "action": "CAB approval required", "severity": "high"}
            ]}},
    ],

    "compliance-management": [
        {"intent": "policy.define", "parameters": {
            "name": "GDPR Compliance", "rules": [
                {"condition": "PII accessed", "action": "log and audit", "severity": "critical"}
            ]}},
        {"intent": "capability.assess", "parameters": {
            "capability_id": "cap-compliance", "criteria": ["gdpr", "sox", "iso27001"]}},
    ],

    "data-governance": [
        {"intent": "policy.define", "parameters": {
            "name": "Data Classification Policy", "rules": [
                {"condition": "PII field", "action": "encrypt at rest", "severity": "critical"}
            ]}},
    ],

    "enterprise-architecture": [
        {"intent": "capability.register", "parameters": {
            "name": "Enterprise Architecture Design", "domain": "architecture",
            "level": "expert", "tags": ["togaf", "archimate"]}},
        {"intent": "knowledge.store", "parameters": {
            "topic": "EA Reference Architecture", "content": "TOGAF ADM phases",
            "tags": ["ea", "togaf"]}},
    ],

    "digital-transformation": [
        {"intent": "process.define", "parameters": {
            "name": "Digital Transformation Roadmap", "steps": [
                "assess", "strategize", "pilot", "scale"]}},
    ],

    "it-audit": [
        {"intent": "policy.define", "parameters": {
            "name": "Audit Trail Policy", "rules": [
                {"condition": "admin action", "action": "log to immutable store", "severity": "high"}
            ]}},
    ],

    "it-finance": [
        {"intent": "capability.register", "parameters": {
            "name": "IT Budget Management", "domain": "finance",
            "level": "advanced", "tags": ["capex", "opex", "cloud-cost"]}},
    ],

    "it-procurement": [
        {"intent": "process.define", "parameters": {
            "name": "Vendor Evaluation", "steps": [
                "rfp", "scoring", "due-diligence", "contract"]}},
    ],

    "it-marketing": [
        {"intent": "knowledge.store", "parameters": {
            "topic": "Tech Product Marketing", "content": "GTM strategy for SaaS",
            "tags": ["marketing", "saas", "gtm"]}},
    ],

    "it-communications": [
        {"intent": "process.define", "parameters": {
            "name": "Incident Communications", "steps": [
                "detect", "draft", "send-update", "resolve-comms"]}},
    ],

    "change-management-it": [
        {"intent": "process.define", "parameters": {
            "name": "Change Management Process", "steps": [
                "initiate", "assess", "approve", "implement", "review"]}},
    ],

    "customer-success-tech": [
        {"intent": "skill.map", "parameters": {
            "title": "Customer Success Manager", "skills": [
                "Account Management", "Churn Prevention", "QBR"]}},
    ],

    "it-training": [
        {"intent": "knowledge.store", "parameters": {
            "topic": "IT Training Curriculum", "content": "Learning paths by role",
            "tags": ["training", "l&d", "certifications"]}},
    ],
}

# Seniority-specific parameter modifiers
SENIORITY_MODIFIERS: dict[str, dict] = {
    "intern": {"level": "basic", "complexity": "low"},
    "junior": {"level": "basic", "complexity": "medium"},
    "mid": {"level": "intermediate", "complexity": "medium"},
    "senior": {"level": "advanced", "complexity": "high"},
    "staff": {"level": "expert", "complexity": "high"},
    "principal": {"level": "expert", "complexity": "very-high"},
    "director": {"level": "expert", "complexity": "strategic"},
    "vp": {"level": "expert", "complexity": "strategic"},
    "cto": {"level": "expert", "complexity": "strategic"},
    "contractor": {"level": "intermediate", "complexity": "medium"},
    "consultant": {"level": "advanced", "complexity": "high"},
    "freelancer": {"level": "intermediate", "complexity": "medium"},
}

GENERIC_INPUTS: list[dict] = [
    {"intent": "capability.register", "parameters": {
        "name": "Core Capability", "domain": "general",
        "level": "intermediate", "tags": ["it", "role"]}},
    {"intent": "skill.map", "parameters": {
        "title": "IT Professional", "skills": ["Communication", "Problem Solving"]}},
]


def get_inputs_for_agent(agent: dict) -> list[dict]:
    """Return the most appropriate test inputs for a given agent metadata dict."""
    role = agent.get("role", "")
    seniority = agent.get("seniority", "mid")
    inputs = ROLE_INPUTS.get(role, GENERIC_INPUTS).copy()

    # Apply seniority modifier to the first input's parameters if applicable
    if inputs and seniority in SENIORITY_MODIFIERS:
        mod = SENIORITY_MODIFIERS[seniority]
        first = dict(inputs[0])
        params = dict(first.get("parameters", {}))
        if "level" in params:
            params["level"] = mod["level"]
        params.setdefault("_seniority", seniority)
        params.setdefault("_complexity", mod["complexity"])
        first["parameters"] = params
        inputs = [first] + inputs[1:]

    return inputs
