# IT Agents Guardrails Platform

A comprehensive system of **10,000 IT role agent definitions** with a unified guardrails engine
that enforces secrets hygiene, package policies, folder structure standards, and human oversight.

---

## What's Included

| Component | Description |
|-----------|-------------|
| **10,000 Agent Definitions** | YAML definitions for technical & non-technical IT roles |
| **Guardrails Engine** | Orchestrates all checks with reporting |
| **Secrets Scanner** | Detects 20+ secret patterns; blocks commits |
| **Package Manager** | Enforces semver policy; flags vulnerable packages |
| **Folder Validator** | Enforces 8 industry-standard project layouts |
| **Human Input Handler** | CLI Q&A, Slack/webhook escalation, audit log |
| **Combined Guardrails YAML** | Single declarative skill file for all guardrails |
| **Connective Config** | Wires all components; supports Vault, Slack, CI/CD |
| **Project Templates** | Scaffolding for Python, Node, ML, Data Pipeline, Terraform |
| **CI Templates** | GitHub Actions, GitLab CI, pre-commit configs |

---

## Agent Categories (50 roles × 200 variants = 10,000 agents)

### Technical (30 categories)
| Category | Primary Stacks |
|----------|---------------|
| Frontend Development | React, Vue, Angular, Svelte, Next.js, Astro |
| Backend Development | FastAPI, Django, Spring, Go, Rust, Rails |
| Fullstack Development | Next.js+Node, T3, SvelteKit, Remix |
| Mobile Development | iOS Swift, Android Kotlin, React Native, Flutter |
| DevOps Engineering | GitHub Actions, GitLab CI, ArgoCD, Jenkins |
| Platform Engineering | Backstage, Crossplane, Internal Developer Platforms |
| SRE Engineering | Prometheus, Grafana, Chaos Engineering |
| Cloud Architecture | AWS, Azure, GCP, Multi-cloud |
| Security Engineering | SIEM, SOAR, Zero Trust, IAM |
| AppSec Engineering | SAST, DAST, OWASP, DevSecOps |
| Cloud Security | CSPM, CNAPP, Wiz, Prisma |
| Penetration Testing | Web, Network, Red Team, Cloud |
| Data Engineering | Spark, Kafka, dbt, Airflow, Snowflake |
| Data Science | Python, R, Statistical Analysis, A/B Testing |
| ML Engineering | PyTorch, MLflow, Kubeflow, BentoML |
| AI/LLM Engineering | LangChain, RAG, Fine-tuning, Agent Design |
| Database Administration | PostgreSQL, MongoDB, Cassandra, Redis |
| Systems Administration | Linux, Windows Server, Ansible, Puppet |
| Network Engineering | Cisco, Juniper, SD-WAN, BGP/OSPF |
| Embedded Systems | C/C++, FreeRTOS, ARM Cortex, STM32 |
| IoT Engineering | MQTT, LoRaWAN, AWS IoT, Edge Computing |
| Blockchain Development | Ethereum, Solana, Smart Contracts, DeFi |
| Game Development | Unity, Unreal Engine, Godot |
| AR/VR Development | OpenXR, ARKit, ARCore, WebXR |
| QA Engineering | Selenium, Playwright, Cypress, Appium |
| Performance Engineering | k6, JMeter, Locust, Profiling |
| Technical Writing | API Docs, Runbooks, Architecture Docs |
| Developer Relations | Community, SDK Design, Advocacy |

### Non-Technical (22 categories)
IT Project Management, Program Management, Scrum Master, Product Management,
Business Analysis, IT Strategy, Enterprise Architecture, IT Governance,
Vendor Management, IT Procurement, IT Finance, IT Audit, Compliance Management,
Change Management, ITSM Management, IT Training, IT Recruiting,
IT Operations Management, IT Marketing, Customer Success, IT Risk Management,
Digital Transformation, Data Governance, IT Communications

---

## Quick Start

### 1. Install dependencies
```bash
pip install pyyaml packaging
```

### 2. Run guardrails on your project
```bash
# Check only (default) — reports violations without blocking
python guardrails/guardrails_engine.py /path/to/project

# Auto-fix where possible (creates missing dirs, suggests fixes)
python guardrails/guardrails_engine.py /path/to/project --mode fix

# Block CI pipeline on violations (use this in CI/CD)
python guardrails/guardrails_engine.py /path/to/project --mode block
```

### 3. Scaffold a new project with standard structure
```python
from guardrails.folder_validator import FolderValidator

fv = FolderValidator()
# project_type: python-service | node-service | ml-project | data-pipeline |
#               infra-terraform | microservice-docker | fullstack-app | generic-project
created = fv.generate_structure('python-service', 'my-api', '.')
print(f"Created {len(created)} files and directories")
```

### 4. Scan for secrets only
```python
from guardrails.secrets_scanner import SecretsScanner

scanner = SecretsScanner()
findings = scanner.scan_directory('/path/to/project')
for f in findings:
    print(f"[{f['severity'].upper()}] {f['description']} in {f['file']}:{f['line']}")
```

### 5. Check package policies
```python
from guardrails.package_manager import PackageManager

pm = PackageManager({"version_policy": "minor", "check_vulnerabilities": True})
findings = pm.check('/path/to/project')
for f in findings:
    print(f"{f['type']}: {f['package']} — {f.get('message', '')}")
```

### 6. Regenerate all 10,000 agents
```bash
cd future-agents
python scripts/generate_agents.py
```

### 7. Build downloadable ZIP
```bash
python scripts/package_zip.py
```

---

## Guardrails Profiles

| Profile | Use Case | Secrets | Packages | Folder | Human Escalation |
|---------|----------|---------|---------|--------|-----------------|
| `standard` | Most teams | warn+block critical | auto minor/patch, ask major | warn | on critical |
| `strict` | Security/regulated roles | block all | ask all upgrades | error+warn | all violations |
| `relaxed` | Dev/sandbox | warn only | minimal checks | warn | on critical only |
| `architect` | Senior/architect roles | block all | ask + rationale | enforce all | all violations |

Set in `config/guardrails_config.yaml`:
```yaml
active_profile: strict
```

---

## CI/CD Integration

### GitHub Actions
Copy `templates/ci/github-actions-guardrails.yml` → `.github/workflows/guardrails.yml`

### GitLab CI
Include `templates/ci/gitlab-ci-guardrails.yml` in your `.gitlab-ci.yml`

### pre-commit (runs before every commit)
Copy `templates/ci/pre-commit-guardrails.yaml` → `.pre-commit-config.yaml`
```bash
pip install pre-commit
pre-commit install
```

---

## Configuration Files

### `config/guardrails_config.yaml`
Runtime settings for all guardrail checks — secrets sensitivity, package policies,
folder structure rules, human escalation, and CI/CD modes.

### `config/connective_config.yaml`
Service integrations: HashiCorp Vault, AWS Secrets Manager, Azure Key Vault,
Slack, webhooks, package registries, GitHub/GitLab, observability.

### `skills/combined_guardrails.yaml`
Declarative skill definitions. All guardrail rules, escalation flows, compliance mappings,
and CI/CD integration points in one file.

---

## Adding Custom Agents

1. Copy `templates/agent-templates/agent_template.yaml`
2. Fill in role details
3. Place in `agents/technical/` or `agents/non-technical/`
4. The engine auto-discovers all YAML files

---

## Adding Custom Guardrail Skills

1. Copy `templates/skill-templates/skill_template.yaml`
2. Define your rules (regex, file checks, or custom scripts)
3. Place in `skills/custom/`
4. Reference in `config/connective_config.yaml` under `skills_registry.additional_skills_dir`

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GUARDRAILS_CONFIG` | Path to config YAML | `config/guardrails_config.yaml` |
| `GUARDRAILS_INTERACTIVE` | Enable interactive CLI prompts | `true` |
| `GUARDRAILS_SLACK_WEBHOOK` | Slack notification webhook URL | — |
| `GUARDRAILS_WEBHOOK_URL` | Generic notification webhook URL | — |
| `GUARDRAILS_WEBHOOK_TOKEN` | Bearer token for webhook auth | — |
| `PLATFORM_ENV` | Environment name | `development` |

---

## Directory Structure

```
future-agents/
├── agents/
│   ├── technical/
│   │   ├── frontend-development/       (~200 agents each)
│   │   ├── backend-development/
│   │   ├── devops-engineering/
│   │   ├── ... (27 more technical categories)
│   ├── non-technical/
│   │   ├── it-project-management/
│   │   ├── ... (21 more non-technical categories)
│   └── agents_index.json               (searchable index)
├── guardrails/
│   ├── guardrails_engine.py            (main orchestrator)
│   ├── secrets_scanner.py              (20+ secret patterns)
│   ├── package_manager.py              (Python/Node/Go/Ruby/Java)
│   ├── folder_validator.py             (8 project layouts)
│   └── human_input_handler.py          (CLI + webhooks)
├── skills/
│   └── combined_guardrails.yaml        (master skill definitions)
├── config/
│   ├── guardrails_config.yaml          (runtime config)
│   └── connective_config.yaml          (integrations)
├── templates/
│   ├── agent-templates/
│   │   └── agent_template.yaml
│   ├── skill-templates/
│   │   └── skill_template.yaml
│   ├── project-structures/
│   │   ├── python-service/
│   │   ├── node-service/
│   │   └── ml-project/
│   └── ci/
│       ├── github-actions-guardrails.yml
│       ├── gitlab-ci-guardrails.yml
│       └── pre-commit-guardrails.yaml
└── scripts/
    ├── generate_agents.py              (generate 10,000 agents)
    └── package_zip.py                  (build downloadable ZIP)
```
