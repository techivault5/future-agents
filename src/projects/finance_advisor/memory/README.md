# Finance Memory Framework + Pluggable SDKs

Agent memory for personal finance, with the same API in **Python**, the
**browser**, and **VS Code** — and the same local-first rule everywhere: your
financial context never leaves the machine.

Educational only. Nothing here is licensed financial advice.

---

## 1 · Memory types

Five types, matching the taxonomy the current agent-memory frameworks converge
on (Letta's tiered context, Mem0/Zep/Cognee's vector+graph split):

| Type | Holds | Lifetime | Example |
|---|---|---|---|
| `working` | current-session scratch | TTL, 1 h default | "comparing 15y vs 20y tenure right now" |
| `episodic` | timestamped events | until pruned | "asked whether the gold dip is a buy window" |
| `semantic` | durable facts | permanent | `take_home=180000`, `risk_tolerance=moderate` |
| `procedural` | learned how-to sequences | permanent | "before any payoff plan: check employer match first" |
| `graph` | entities + typed relations | permanent | `debt:HDFC card —owes→ ₹84,000` |

Every record carries importance, confidence, provenance, access counts and a
`sensitive` flag. Sensitive records are **redacted by default** in recall
output, exports, logs and prompt blocks — income and balances stay out of
anything you might paste elsewhere.

**Recall is hybrid**, blending four signals (weights are module constants):

```
score = 0.55·cosine + 0.20·keyword_overlap + 0.15·recency_decay + 0.10·importance
```

`consolidate()` promotes themes recurring across ≥3 episodes into semantic
facts, linked back to their sources. `forget()` drops expired and never-accessed
low-importance records.

## 2 · Backends

| Backend | Storage | Durable | Deps | Use it when |
|---|---|---|---|---|
| `InMemoryBackend` | dict | no | none | tests, one-shot scripts |
| `SqliteBackend` | one file + FTS5 index | yes | stdlib | the normal choice, local-first |
| `GraphBackend` | adjacency over any backend | inherits | none | entity/relation questions |

`GraphBackend.to_cypher()` exports the memory graph as Cypher, so it lifts into
**Kuzu** (embedded, which is what Cognee/Graphiti use for local-first graphs),
Neo4j or FalkorDB unchanged when you outgrow the embedded store.

## 3 · Embedders — CPU, GPU, NPU, Metal, browser

The default embedder needs no model at all; every other option is a drop-in
upgrade behind the same one-method protocol.

| Embedder | Compute | Install | Quality | Notes |
|---|---|---|---|---|
| `HashingEmbedder` **(default)** | CPU, trivial | none | lexical | Identical algorithm in Python and JS → **vectors are portable across runtimes** |
| `SentenceTransformerEmbedder` | CPU / CUDA / Metal | `.[localnlp]` | semantic, best | MiniLM-L6 ≈ 90 MB; torch is the heavy part |
| `OllamaEmbedder` | GPU / Metal / CPU | Ollama daemon | semantic | `nomic-embed-text`; stays on localhost |
| `OnnxEmbedder` | **NPU** / CPU / DirectML | `.[localnlp]` | semantic | Same ONNX graph reused by Transformers.js in the browser |
| `TransformersJsEmbedder` (JS) | **browser** WebGPU / WASM | npm, optional | semantic | v4's WebGPU rewrite is ~4× faster with a much smaller bundle |

Because the hashing embedder is lexical, `"what is my income"` would not match
`take_home=180000` on its own — so a small **finance alias table**
(`aliases.py`, mirrored in JS) expands query terms at query time. Stored vectors
stay untouched, so switching to a real embedding model later needs no re-index.

### Local inference runtimes compared

`sdk.runtimes()` returns this as data; `sdk.capabilities()` reports what *your*
machine can actually run. Figures are mid-2026 order-of-magnitude guidance, not
benchmarks.

| Runtime | Target | Best at | Setup | Watch out |
|---|---|---|---|---|
| **llama.cpp** | CPU | Quantised models on commodity hardware; the only engine treating CPU as first-class (AVX2/AVX-512, NEON) | medium | You tune quantisation and threads |
| **Ollama** | GPU (+CPU/Metal fallback) | Default single-developer choice; one-command install, OpenAI-compatible API | low | Wraps llama.cpp/MLX — less knob-level control |
| **vLLM** | GPU (server) | Multi-user serving: PagedAttention + continuous batching, ~16-20× Ollama under concurrency | high | Overkill for one household |
| **MLX** | Apple Metal | Fastest per watt on Apple Silicon; Ollama 0.19+ uses it on M-series. Unified memory = RAM is VRAM | low | Apple-only |
| **ONNX Runtime** | **NPU** (DirectML / QNN / OpenVINO) | Embeddings and rerankers at very low power on Copilot+ / Snapdragon | medium | Provider support varies by OS and chip |
| **Transformers.js** | **Browser** (WebGPU → WASM) | Client-side embeddings with zero server; WebGPU can be 10-15× WASM | low | First load downloads and caches weights |
| **sentence-transformers** | CPU / CUDA / Metal | Best local embedding quality for least code | low | Pulls in torch |

## 4 · The SDKs

Both SDKs expose the same surface, so integration code has the same shape
wherever it runs, and `export()` on one side imports on the other.

| Capability | Python | JavaScript (browser / Node / VS Code) |
|---|---|---|
| Write | `sdk.remember(text, type=…, sensitive=…)` | `sdk.remember(text, { type, sensitive })` |
| Recall | `sdk.recall(q, limit)` | `sdk.recall(q, limit)` |
| Prompt block | `sdk.context(q)` | `sdk.context(q)` |
| Profile | `sdk.profile()` | `sdk.profile()` |
| Maintain | `sdk.consolidate()` / `sdk.forget()` | `sdk.consolidate()` / `sdk.forget()` |
| Skills | `sdk.advise("loans", **args)` | `sdk.advise('loans', args)` |
| Runtimes | `sdk.runtimes()` / `sdk.capabilities()` | `FinanceMemorySDK.runtimes()` / `.capabilities()` |
| Transfer | `sdk.export()` / `sdk.import_records()` | `sdk.export()` / `sdk.importRecords()` |

### Python

```python
from projects.finance_advisor.memory import FinanceMemorySDK

sdk = FinanceMemorySDK(store="sqlite", path="data/memory.db")
sdk.remember("take_home=180000", tags=["profile"], sensitive=True)
sdk.recall("what do I earn")                     # → the take_home fact, redacted
sdk.advise("loans", principal=3_500_000, annual_rate_pct=8.6, months=240)
```

### Browser

```html
<script type="module">
  import { FinanceMemorySDK } from './sdk/js/finance-memory.mjs';
  const sdk = new FinanceMemorySDK({ store: 'local' });   // localStorage
  sdk.remember('risk_tolerance=moderate', { tags: ['profile'] });
  console.log(sdk.advise('mutual_funds', { monthly: 25000, years: 15 }));
</script>
```

A working demo page ships with it — write memories, watch the score
components, run every skill, see which runtimes the browser offers:

```bash
uvicorn projects.finance_advisor.app:app --port 8600
# then open http://localhost:8600/sdk/js/demo.html
```

Serve it over http, don't open the file directly: browsers refuse to load ES
modules over `file://`, so the app mounts `memory/sdk/` at `/sdk` for this.

### VS Code

`sdk/vscode/` is a complete extension (no bundler, no dependencies) that loads
the same `.mjs` and persists to extension storage. Commands:

* Finance Advisor: **Ask a finance question** (recall memory)
* Finance Advisor: **Remember a fact**
* Finance Advisor: **Run a skill**
* Finance Advisor: **Show local model runtimes**
* Finance Advisor: **Export memory as JSON**

Load it with `code --extensionDevelopmentPath=projects/finance_advisor/memory/sdk/vscode`.

### HTTP (the existing dashboard)

`app.py` mounts the SDK, so the dashboard and any other client share one store:

```
GET  /api/memory/stats            GET  /api/memory/recall?q=…
POST /api/memory/remember         GET  /api/memory/profile
POST /api/memory/consolidate      GET  /api/memory/export
GET  /api/skills                  POST /api/skills/{name}
GET  /api/runtimes
```

## 5 · Skills

| Skill | Covers |
|---|---|
| `loans` | EMI maths, affordability ceilings (≤40% total, ≤30% housing), avalanche vs snowball, prepay vs invest |
| `mutual_funds` | SIP future value, step-up SIP, goal-required SIP, direct-vs-regular cost drag, category guidance |
| `crypto` | Allocation caps by risk tolerance, India 30% VDA tax + 1% TDS after-tax maths, custody, scam tests |
| `capital_gains` | Equity LTCG 12.5% above ₹1.25 L, STCG 20%, holding-period check, exemption harvesting |
| `taxes` | Old vs new regime pointers, 80C/80CCD(1B) capacity, asset-wise treatment table, when to escalate to a CA |

Every skill returns its own arithmetic so you can check it by hand, writes what
it learns to memory, and carries the not-advice disclaimer. Tax constants are
FY 2025-26 and sit in one block at the top of `skills.py` — verify them against
the current year before relying on any number.

## 6 · What this deliberately does not do

* No specific securities, tickers or funds are recommended — asset *classes* only.
* No promised or guaranteed returns; assumed rates are labelled as assumptions.
* No cloud calls, no telemetry, no account linking.
* Nothing files, trades, or transfers anything.

Large sums, property gains, ESOPs, foreign assets or residency changes need a
fee-only fiduciary or chartered accountant — not an agent.
