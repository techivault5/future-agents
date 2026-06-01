# Python Service — Project Structure Template

Standard structure for Python microservices and APIs.

```
python-service/
├── src/
│   └── {package_name}/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── routes/
│       ├── services/
│       ├── models/
│       ├── schemas/
│       ├── repositories/
│       └── utils/
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── docs/
│   └── architecture.md
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── guardrails.yml
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── Makefile
└── README.md
```

## Guardrails Applied
- **NO_SECRETS**: Blocks .env files, credential files
- **PACKAGE_MANAGEMENT**: Enforces semver ranges in pyproject.toml
- **FOLDER_STRUCTURE**: Validates src/, tests/, docs/ exist

## Quick Start
```bash
cp .env.example .env
make install
make test
make run
```
