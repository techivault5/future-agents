# SQL Server Service — Project Structure Template

Standard structure for services backed by Microsoft SQL Server or Azure SQL.

```
sqlserver-service/
├── src/
│   └── {package_name}/
│       ├── __init__.py         (Python) or Program.cs (C#)
│       ├── config.py
│       ├── db/
│       │   ├── connection.py   ← reads from os.environ, NEVER hardcoded
│       │   ├── migrations/     ← Flyway / Alembic / EF Migrations
│       │   └── seed/
│       ├── models/
│       ├── repositories/
│       ├── services/
│       └── api/
├── tests/
│   ├── unit/
│   └── integration/            ← uses testcontainers/localdb
├── migrations/                 ← SQL migration scripts (numbered)
│   ├── V001__initial_schema.sql
│   └── V002__add_indexes.sql
├── scripts/
│   ├── setup_db.sh
│   └── seed_data.py            ← dev seed (no real data)
├── docs/
│   ├── architecture.md
│   ├── data-dictionary.md      ← table/column descriptions
│   └── er-diagram.png
├── .github/workflows/
│   └── ci.yml
├── Dockerfile
├── docker-compose.yml          ← includes mssql server for local dev
├── .env.example                ← NEVER .env
├── .gitignore
├── pyproject.toml              ← or *.csproj
└── README.md
```

## SQL Server Guardrails

### Secrets — NEVER hardcode connection strings
```python
# ❌ NEVER
conn = pyodbc.connect("Server=prod;Password=MyPass123")

# ✅ ALWAYS
conn_str = (
    f"Server={os.environ['MSSQL_SERVER']};"
    f"Database={os.environ['MSSQL_DATABASE']};"
    f"UID={os.environ['MSSQL_USER']};"
    f"PWD={os.environ['MSSQL_SA_PASSWORD']};"
    "Encrypt=yes;TrustServerCertificate=no;"
)
conn = pyodbc.connect(conn_str)
```

### SQL — ALWAYS parameterized queries (prevents injection)
```python
# ❌ NEVER (SQL injection risk)
cursor.execute(f"SELECT * FROM Users WHERE id = {user_id}")

# ✅ ALWAYS
cursor.execute("SELECT * FROM Users WHERE id = ?", (user_id,))
```

### C# / Entity Framework
```csharp
// ❌ NEVER in appsettings.json
// "ConnectionStrings": { "Default": "Server=prod;Password=..." }

// ✅ Use User Secrets (dev) or Azure Key Vault (prod)
builder.Configuration.AddUserSecrets<Program>();  // dev
builder.Configuration.AddAzureKeyVault(...);       // prod
```

### Azure SQL — Use Managed Identity (no passwords at all)
```python
from azure.identity import DefaultAzureCredential
credential = DefaultAzureCredential()
token = credential.get_token("https://database.windows.net/.default")
# Pass token to pyodbc — no password needed
```

## Guardrails Commands

```bash
# Check for hardcoded SQL Server credentials
python guardrails/guardrails_engine.py . --mode check

# Patterns detected:
# - MSSQL_SA_PASSWORD=<value>
# - Server=...;Password=<value>
# - User Id=sa;Password=<value>
# - mssql://user:pass@host
# - sqlserver://user:pass@host
```

## Local Dev with Docker

```yaml
# docker-compose.yml
services:
  sqlserver:
    image: mcr.microsoft.com/mssql/server:2022-latest
    environment:
      ACCEPT_EULA: "Y"
      MSSQL_SA_PASSWORD: "${MSSQL_SA_PASSWORD}"   # from .env
    ports:
      - "1433:1433"
```

## Guardrails Applied
- **SQLSERVER_ADO_CONNSTR**: Detects `Server=...;Password=...` patterns
- **SQLSERVER_SA_PASS**: Detects inline `User Id=...;Password=...`
- **DB_PASSWORD_INLINE**: Detects `MSSQL_SA_PASSWORD=<value>` in code
- **DB_CONNECTION_STRING**: Detects `mssql://` and `sqlserver://` URLs
- **PACKAGE_MANAGEMENT**: Enforces semver on pyodbc, sqlalchemy, pymssql
- **FOLDER_STRUCTURE**: Requires migrations/, docs/data-dictionary.md
