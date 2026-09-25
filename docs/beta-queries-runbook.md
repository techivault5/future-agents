# Beta Queries — runbook for three datasources

Follow the steps in order. **Each one ends with a check; do not start the next
step until that check passes.** If a check fails, the fix is in the same step.

---

## 0. What was actually wrong

This is not a configuration problem on your laptop. The build had four gaps,
all fixed in this version:

1. **The query path could not read Neo4j or Redis.** The crawl wrote the catalog
   to both, and nothing read it back — `Neo4jGraph` could write tables but had
   none of the methods the orchestrator calls, and the Redis profile had no
   reader at all. Any glue that bridged that is the likely source of your random
   errors. **Now:** the crawl output is loaded into memory once at startup, and
   no question ever waits on Neo4j or Redis.
2. **Table selection ignored what routing had found.** Routing could see that
   "India" lives in `t_emp_m.country_name`, then table selection ranked
   `t_emp_m` at zero because its name shares no word with the question.
   **Now:** a table holding a value the question names is ranked first.
3. **The model never saw what columns contain.** It got names and types only,
   so it guessed at values. **Now:** each column shows up to four real values —
   `emp_status (VARCHAR) e.g. ACTIVE, TERMINATED`.
4. **The model call gave up too early and said the wrong thing.** 8-second
   timeout, 1500-token cap, no retry, and every failure reported as "I couldn't
   turn that into a query". **Now:** 45 s and 4000 tokens by default, one retry,
   and a failure says what failed.

---

## 1. Get the code

```bash
git fetch origin claude/beta-queries-text-to-sql-jy7u30
git checkout claude/beta-queries-text-to-sql-jy7u30
git pull
```

Or unzip `beta-queries.zip` if you are working from the bundle.

**Check:** `scripts/beta_queries_ask.py` exists.

---

## 2. Install

```bash
python scripts/beta_queries_bootstrap.py
```

Then install the driver for **each engine you use** — they are not installed by
default, because each one drags in system libraries you may not need:

| Engine | Install |
|---|---|
| SQL Server | `pip install -e ".[beta_queries_sqlserver]"` **and** ODBC Driver 18 (Windows: from Microsoft; macOS: `brew install unixodbc` + msodbcsql18) |
| Postgres | `pip install "psycopg[binary]"` |
| Snowflake | `pip install snowflake-connector-python` |
| Databricks | `pip install databricks-sql-connector` |
| MySQL | `pip install mysql-connector-python` |
| DuckDB | already installed |

Activate the environment for every step below:

```bash
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\activate             # Windows
```

**Check:** the bootstrap ends with `[  OK  ] everything works`. Whether each
driver really loads is verified in step 6.

---

## 3. Set the environment

Credentials go in the environment, never in a file you commit. Five values for
the model and your three sources, plus two optional limits.

**PowerShell (Windows):**

```powershell
$env:LUNA_BASE_URL   = "https://REPLACE_ME/v1"
$env:LUNA_API_KEY    = "REPLACE_ME"
$env:LUNA_MODEL      = "REPLACE_ME"          # the model id your endpoint expects
$env:BQ_DSN_HRDB     = "REPLACE_ME"
$env:BQ_DSN_SALESDB  = "REPLACE_ME"
$env:BQ_DSN_FINANCEDB = "REPLACE_ME"
```

**bash / zsh:**

```bash
export LUNA_BASE_URL="https://REPLACE_ME/v1"
export LUNA_API_KEY="REPLACE_ME"
export LUNA_MODEL="REPLACE_ME"
export BQ_DSN_HRDB="REPLACE_ME"
export BQ_DSN_SALESDB="REPLACE_ME"
export BQ_DSN_FINANCEDB="REPLACE_ME"
```

What a DSN looks like, per engine:

| Engine | `BQ_DSN_*` value |
|---|---|
| SQL Server | `DRIVER={ODBC Driver 18 for SQL Server};SERVER=host;DATABASE=db;Trusted_Connection=yes;Encrypt=yes;` |
| Postgres | `postgresql://user@host:5432/db` |
| Snowflake | `{"account":"REPLACE_ME","user":"REPLACE_ME","authenticator":"externalbrowser","warehouse":"REPLACE_ME","database":"REPLACE_ME"}` |
| Databricks | `{"server_hostname":"REPLACE_ME","http_path":"REPLACE_ME","access_token":"REPLACE_ME"}` |
| MySQL | `{"host":"REPLACE_ME","user":"REPLACE_ME","password":"REPLACE_ME","database":"REPLACE_ME"}` |
| DuckDB | a file path |

Use a **read-only** account wherever you can. The app only ever reads, and a
read-only principal makes that true even if something upstream goes wrong.

Optional limits — leave them unset unless you have measured a reason:

```bash
export BQ_LLM_TIMEOUT_SECONDS=45     # was 8; the main cause of "it stops responding"
export BQ_LLM_MAX_TOKENS=4000        # was 1500; long SQL was being cut off
```

**Check:** `python scripts/beta_queries_crawl.py --dry-run` shows `dsn: set` for
all three.

---

## 4. Describe your three sources

Edit `data/config/beta_queries_sources.yaml`. The example file ships with
someone else's databases — replace every source with yours:

```yaml
version: 1

defaults:
  profile_values: true
  max_distinct: 500     # columns with more distinct values than this are not indexed
  sample_limit: 25
  max_value_len: 64

sources:
  - id: hrdb                        # any short name; you will type it with --source
    dialect: sqlserver              # sqlserver | postgres | snowflake | databricks | mysql | duckdb
    dsn_env: BQ_DSN_HRDB            # the NAME of the variable from step 3, not its value
    description: >
      HR warehouse. Employees, departments, headcount by country.
    subject_areas: [people, headcount]
    synonyms:
      people: emp                   # the word people type -> a word in your table names
      employees: emp
      staff: emp
      headcount: emp
      department: dept

  - id: salesdb
    dialect: snowflake
    dsn_env: BQ_DSN_SALESDB
    description: Sales orders and revenue by region and product line.
    synonyms:
      revenue: amount
      sales: orders

  - id: financedb
    dialect: databricks
    dsn_env: BQ_DSN_FINANCEDB
    description: General ledger. Spend by cost centre, OPEX and CAPEX.
    synonyms:
      spend: amount
      expenses: ledger
```

**`synonyms` is the setting that matters most.** It maps the words your users
type to the words in your table and column names. If your tables are called
`T_HR_EMP_M` and people ask about "staff", nothing matches until you write
`staff: emp`. Look at your real table names and write the ten or twenty words
people actually use. You can edit synonyms later without re-crawling.

**Check:** `python -c "import yaml; yaml.safe_load(open('data/config/beta_queries_sources.yaml'))"`
prints nothing (no error).

---

## 5. Crawl

```bash
python scripts/beta_queries_crawl.py
```

This reads each database's structure and samples the values in every
categorical column, writing two files per source into `.bq-catalog/`. It must
run **on the laptop that answers questions**, or you must copy `.bq-catalog/`
there. Re-run it when a database's structure changes.

Expected, one line per source:

```
hrdb: 2 base tables, 0 views skipped, 1 joins, 1 default filters, 8 indexed values
salesdb: 1 base tables, ...
financedb: 1 base tables, ...
```

**Check:** `ls .bq-catalog/` shows a `.catalog.json` and a `.profile.json` for
every source, and no line printed `!`.

---

## 6. Check every source is ready

```bash
python scripts/beta_queries_ask.py --check
```

```
source         tables   cols  w/vals  values  synonyms  dsn
-----------------------------------------------------------
hrdb                2      7       3       8         5  set
                connected — SELECT 1 ok
salesdb             1      5       3       7         3  set
                ~ main.fct_orders: order_status looks like a status column but no value reads as active — confirm which value to keep
                connected — SELECT 1 ok
financedb           1      5       3       7         3  set
                connected — SELECT 1 ok

ok — every source is ready
```

`--check` **opens a real connection** to each source and runs `SELECT 1`. That
one round trip proves the driver is installed, the DSN is well-formed, the VPN
is up and the credentials work — before any question is asked. A failure is
printed with its cause:

```
salesdb             1      5       3       7         3  set
                ! the snowflake driver is not installed — pip install snowflake-connector-python
financedb           1      5       3       7         3  set
                ! cannot connect: OperationalError: …
```

What each column means, and what to do when it is zero:

| Column | If it is 0 |
|---|---|
| `w/vals` — columns with sampled values | the model will guess what columns hold. Crawl with `profile_values: true`; confirm your account can `SELECT` the tables |
| `values` — the value index | questions naming a value ("India", "EMEA") cannot find this source. Same fix |
| `synonyms` | business words will not match your table names. Step 4 |
| `dsn` says `MISSING` | set that variable (step 3) |
| `! … driver is not installed` | run the `pip install` it names (step 2) |
| `! cannot connect: …` | DSN, VPN or credentials — the message says which |

Lines starting `!` are problems. Lines starting `~` are **decisions** — see step 9.

**Check:** the last line reads `ok — every source is ready`.

---

## 7. Ask one question, pinned, with the diagnostic on

Pin it to the source you know holds the answer, so routing is not a variable yet:

```bash
python scripts/beta_queries_ask.py "how many employees are in India" --source hrdb --debug
```

The output has four blocks. Read them in order:

**1. Routing** — the score for every source and why. With `--source` this only
explains; it does not decide.

**2. Tables considered** — the tables ranked for the question, with reasons.
The one marked `<- used` should be the table you expected. The strongest reason
is `holds the value in: <column>`.

**3.1 What the model was sent** — the schema cards, verbatim. **Look for
`e.g.`** after the columns:

```
country_name (VARCHAR)  e.g. India, Brazil, Germany
emp_status (VARCHAR)  e.g. ACTIVE, TERMINATED
```

No `e.g.` anywhere means the crawl sampled no values — back to step 5.

**4.1 What the model replied** — `stop reason`, `latency`, tokens, and the raw
reply. (`3.2` / `4.2` appear when the call was retried after a network failure, or repaired after an unusable reply.)

**Check:** an answer with a number, and the SQL looks like what you would write.

---

## 8. Reading a bad result

| What you see | Where to look | Fix |
|---|---|---|
| `I couldn't get an answer from the model — the model took longer than …` | block 4, `latency` | raise `BQ_LLM_TIMEOUT_SECONDS`; check the VPN |
| `… cut off at BQ_LLM_MAX_TOKENS` | block 4, `stop reason length` | raise `BQ_LLM_MAX_TOKENS` |
| `… credentials are missing or were rejected` | — | `LUNA_API_KEY`, `LUNA_BASE_URL`, `LUNA_MODEL` — retrying will not help |
| `… could not be reached` | — | `LUNA_BASE_URL`, network, proxy |
| `Nothing you have access to covers that` | block 2 is empty | add a synonym for the question's key word (step 4) |
| right source, **wrong table** | block 2 | synonym that names the right table; or a `~` decision |
| right table, **wrong column** | block 3 | is the column's `e.g.` list there? if not, re-crawl |
| a number that is **too high** | the SQL | a status filter is missing — step 9 |
| `Two sources could answer that. Which do you mean?` | block 1 | two sources scored within 20 points — pin with `--source`, or add synonyms |

---

## 9. Decide the `~` filters

A `~` line in `--check` is a status column where the crawl could not tell which
value means "current":

```
~ main.fct_orders: order_status looks like a status column but no value reads as active
```

It is **not** applied, because guessing would silently change every number. It
matters: in testing, "total revenue in EMEA" returned **175.25** with no filter
and **100.00** with `order_status = 'SHIPPED'` — the difference is a cancelled
order. Decide it once, under the source in `sources.yaml`:

```yaml
  - id: salesdb
    ...
    default_filters:
      main.fct_orders: "order_status = 'SHIPPED'"
```

It is applied to every question on that table unless the user asks otherwise,
and shown to them as an assumption with the answer.

**Check:** the same question now returns the number you expect.

---

## 10. Unpin

Once pinned questions answer correctly, drop `--source` and watch block 1:

```bash
python scripts/beta_queries_ask.py "how many employees are in India" --debug
```

Routing is confident when the top source leads the next by **more than 20
points** — the router's own margin. Closer than that and it asks "which do you
mean?" instead of guessing. Add synonyms that separate the sources, or keep
pinning for that kind of question.

**Check:** ten representative questions route to the right source unpinned.

---

## 11. Where Neo4j and Redis fit now

**Neither is needed to answer questions.** The catalog lives in memory, loaded
from `.bq-catalog/` at startup.

- **Neo4j** stays useful as the durable store the Airflow DAG writes, and as the
  home of curated metrics and learned joins. To use its join graph instead of
  the crawl's:

  ```bash
  export BQ_NEO4J_URI="bolt://REPLACE_ME:7687"
  export BQ_NEO4J_USER="REPLACE_ME"
  export BQ_NEO4J_PASSWORD="REPLACE_ME"
  python scripts/beta_queries_ask.py "..." --graph-from-neo4j --debug
  ```

  It is still loaded **once** into memory. Column values always come from
  `.bq-catalog/`, because Neo4j never stored them.
- **Redis** is not read at all in this setup. The DAG still publishes to it, for
  a future shared cache.

**Take them out of the picture while you get answers right.** Every network hop
in the request path was another way to fail at random.

---

## 12. Errors you may hit

| Error | Cause | Fix |
|---|---|---|
| `no *.catalog.json in … — run the crawl first` | step 5 not done, or done elsewhere | run the crawl on this laptop |
| `no datasource is ready to answer questions — hrdb: BQ_DSN_HRDB is not set` | step 3 | set it in **this** terminal |
| `the snowflake driver is not installed — pip install snowflake-connector-python` | step 2 table | run exactly the command it names |
| `cannot connect: …` in `--check` | DSN, network or credentials | fix what the message names; re-run `--check` |
| `ImportError: libodbc.so.2` | SQL Server extra without the system ODBC library | install unixODBC / ODBC Driver 18 |
| `(skipped financedb: not crawled yet)` | added to `sources.yaml` after the crawl | `python scripts/beta_queries_crawl.py --source financedb` |
| `Python 3.10 is too old` | needs 3.11+ | install 3.11 and re-run the bootstrap with it |

If an error is not in this table, run the same question with `--debug` and
send the whole output. Everything needed to find the cause is in it.
