# Throughline — Product & Interface Brief

> Working codename. A ticketing / team-and-project-management product built
> around one metric — time from **filed** to **finished** — with an AI teammate
> that carries context across the whole lifecycle.

Rendered version (palette, typography, UI mockups):
<https://claude.ai/code/artifact/b1e1e871-56e0-4a1c-8c2c-ba9ea72aa934>

---

## 1 · Thesis

Asana, Jira, Linear and GitHub Issues compete on how fast you can *file* work.
Nobody competes on the days a ticket spends half-understood, waiting for a human
to re-read the thread. Active work is hours; calendar life is days or weeks. The
difference is the cost of reloading context.

An AI teammate is valuable here not because it writes code, but because it is
the only participant that has read everything and can hand each person exactly
the state they are missing.

**Three principles**

| # | Principle | Consequence |
|---|-----------|-------------|
| 01 | State is derived, not dragged | Commits, deploys, CI, approvals push status forward. Manual status changes are exceptions. |
| 02 | Every generated claim is sourced | Inline provenance chips back to the comment / commit / log line. Unsourced sentences are not written. |
| 03 | The teammate has a seat, not a sidebar | Assignable, mentionable, has working hours, consumes capacity, files a weekly report on itself. |

Counter-position: most AI-in-PM shipping today is a summarize button plus a
natural-language filter. Neither moves cycle time, so neither survives
procurement. Every feature below is chosen because it removes a wait state.

---

## 2 · Object model (prerequisite for good summaries)

Trackers store one undifferentiated comment stream, so a model has to guess what
is a decision, what is noise, and what is still true. Separate them at write time.

| Entity | Holds | Why it earns its own table |
|--------|-------|----------------------------|
| `Ticket` | Intent, acceptance criteria, severity, owner, state | The stable contract; barely changes after triage |
| `Thread` | Human discussion, typed per message | Tagged `question` / `answer` / `decision` / `blocker` / `fyi`; model-assigned, human-correctable |
| `Signal` | Commit, PR, deploy, CI run, alert, email, transcript | Machine evidence, never mixed into the human thread; drives auto state transitions |
| `Decision` | Statement, author, timestamp, superseded-by | Promoted out of the thread so a brief can state the current approach; supersession keeps briefs correct |
| `Run` | AI action: inputs, tools, cost, diff, confidence, revert token | Auditable record with undo — the trust substrate |
| `Blocker` | Typed edge: person / ticket / external / decision | Typed blockers make nudges specific and chains traversable |

**Payoff:** a brief assembles from `Decision` + open `Blocker` + recent `Signal`
— small, structured, cheap — instead of stuffing 400 comments into a context
window. Faster, cheaper, reliably correct.

---

## 3 · The digital teammate

### Six roles, hired separately

Don't ship one omniscient assistant. Ship named roles staffed onto a project,
each with its own permissions and success metric.

| Role | Does | Measured on |
|------|------|-------------|
| **Triage** | Severity, component, duplicates, assignee suggestion with reasoning | Triage-to-owner time; human override rate |
| **Scribe** | Standing brief, decision promotion, closure records | Human edits to the brief |
| **Analyst** | Prior art, runbooks, owning team, last toucher of the code | Click-through; time-to-first-action |
| **Implementer** | Bounded changes end to end: branch, patch, tests, PR | Merge rate without human rework |
| **Reporter** | Daily brief, weekly stakeholder narrative, exec answers | Status meetings removed |
| **Watch** | Stall detection, SLA risk, dependency chains, aging past p75 | Breaches prevented vs false alarms |

### The autonomy dial

Set **per capability, per project**, visible on every ticket.

1. **Suggest** — proposes in a side panel; nothing written until a human clicks.
2. **Draft** — writes into fields marked as drafts; nothing visible or sent until accepted.
3. **Act with undo** — acts, posts the run record, holds one-click revert for 24h; owner notified, not asked.
4. **Act** — full autonomy inside declared scope; still logged, revertible, bound by escalation triggers.

**Always escalates:** auth · payments · PII/PHI · irreversible migration ·
confidence < 0.7 · spend over cap.

Promotion up the dial is a management decision backed by acceptance and revert
rates — not a toggle flipped on faith.

### Two non-negotiables

- **Run records.** Every action expands into what it read, tools called, what
  changed, cost, confidence — with a revert button. Teams adopt AI because they
  can see what it did at 3am and put it back.
- **Escalation as first-class UI.** When it stops, it posts a question card:
  what it was doing, the specific ambiguity, 2–3 options, its recommendation.
  One click resumes from the pause point.

Give each teammate a **profile page** — tickets touched, hours returned,
acceptance rate, revert rate, spend vs budget, escalations raised.

---

## 4 · Ticket summarization — three summaries, three jobs

"Summarize this ticket" is one button doing three unrelated jobs badly.

1. **The Standing Brief** — always current, top of ticket. Six lines: what this
   is, why it matters, current approach, who is blocked on what, next concrete
   action. Regenerated on *state change* (decision / blocker / merged PR), never
   on every comment — keeps it cheap and stops it thrashing.

2. **Since You Last Looked** — *the highest-value feature in this document.*
   A delta computed against **each reader's own** last read: what changed, what
   it means for them, whether they now owe someone something. Makes a
   200-comment ticket re-enterable in 15 seconds. Ship this before anything else
   AI-shaped; it's what people form a habit around.

3. **The Closure Record** — drafted at close. Root cause, what fixed it, how it
   was verified, what to watch, follow-ups filed as real linked tickets. Makes
   the ticket valuable in eight months, and turns ticket history into the
   prior-art corpus the Analyst reads from.

**Supporting mechanics**

- **Provenance chips**, not footnotes — hover previews the source, click jumps to it.
- **Freshness always visible** — "current as of signal #61 · 2 new since". A stale
  summary presented as current is the failure mode that kills trust in the feature.

---

## 5 · Screens & information architecture

**Navigation:** narrow left rail for scope; one command surface (`⌘K`) that is
simultaneously search, launcher and AI prompt. **Do not build a separate chat
panel** — the moment AI lives in its own tab it becomes a place people visit
instead of a capability that follows them.

| Surface | What it is |
|---------|-----------|
| **Your Line** | Home. Not a chart dashboard — one prioritized queue answering "what should I touch next?". Ordered by consequence: you're the blocker → SLA risk → aging → new. Each row carries its own delta summary so it's actionable without opening. |
| **The Ticket** | Three columns. Left: state, standing brief, decision timeline. Centre: description + typed thread, AI runs inline as expandable records. Right: linked PRs, dependencies, prior art, runbook. |
| **The Project** | Board · List · Timeline · **Load**. Load is the differentiator: committed hours vs real capacity per person, with the teammate occupying a real column. Over-commitment visible before the sprint. |
| **Flow** | Cumulative flow, aging WIP, time-in-status. Not a reporting afterthought — the aging chart *is* a work queue; every bar clicks through. |

**Ticket age as colour.** The left stripe on every row encodes age: fresh work in
verdigris, oxidizing through bronze to rust. One piece of ornament, encoding the
metric the product is built on, legible across a hundred rows.

**Interaction rules**

- Keyboard-first: `j`/`k` navigate, `a` assign, `s` status, `.` AI actions, `⌘K`
  everything. Optimistic updates <100ms, offline queue.
- **AI output is visually distinct, always** — accent-soft ground, `AI` chip,
  author attribution. Never mimics a human comment. Accepting a draft converts
  it to content authored by the accepter, and the record says so.

---

## 6 · Where the days get removed (filed → finished)

A real sequence. Each stage names the wait state it deletes.

### 1. Intake — kills "this ticket is unusable"
- **Paste anything, get a ticket.** Slack thread, forwarded email, screenshot,
  stack trace, call transcript → title, description, repro, severity, owner, as
  an editable draft.
- **Completeness score at file time.** A P1 without repro steps doesn't submit;
  the form asks the two missing questions inline.
- **Duplicate + prior-art detection before submit.** Half of support tickets die
  here, in seconds, without entering the queue.

### 2. Triage — kills the morning triage meeting
- Auto-classification **with stated reasoning**, so overrides are corrections the
  model learns from rather than arguments.
- Assignee suggestion grounded in evidence: last toucher, similar-ticket
  resolver, capacity this week, on-call.
- **Drafted first response** queued for one-click send — first-response time is
  usually what the SLA is written against.

### 3. Ready — kills "I opened it and didn't know where to start"
- **Definition-of-ready auto-evaluated**: criteria present, dependencies
  resolved, design linked, environment available.
- **Context assembled in advance**: relevant files, last three similar PRs,
  runbook section, owning team per dependency.
- **Branch + scaffold on accept**; draft PR carries the standing brief as its body.

### 4. In flight — kills status theatre and silent stalls
- **Signal-driven state** — nobody drags cards, so the board is accurate.
- **Typed stall detection** with a *specific* question ("the vendor quota you
  were waiting on was approved Friday; resume?"), never "any update?".
- **Traversable blocker chains** — see you're waiting on a decision two tickets
  away, and ping its owner from here.
- **Conditional snooze** — "wake me when CI is green" / "when PAY-2214 closes".
  Wall-clock snoozing is guessing; conditional snoozing is scheduling.

### 5. Verify — kills the reopen
- Acceptance criteria as checkable items, ticked by test/deploy events where possible.
- **Reopen-risk flag** — tickets resembling past reopens get held for verification.
  Reopen rate is what silently invalidates a cycle-time win.

### 6. Close — kills the Friday cleanup
- **The close queue**: everything merged, deployed and verified, each with a
  drafted closure record, approved in one screen.
- **Follow-ups become real linked tickets** at close — scoped and estimated,
  not a sentence in a comment nobody reads again.

### 7. Report — kills the status meeting
- **Async standup digest** per team each morning: what moved, what stalled, what
  needs a decision today.
- **Stakeholder narrative** weekly in plain language, plus a live shareable
  status page for people who should never get a login.

**The gains stack.** A ticket filed badly Monday / triaged Wednesday / started
Thursday / blocked over the weekend / closed the following Friday becomes one
filed well, started same-day, unblocked by a specific nudge, closed with an
approval click.

---

## 7 · Alerts — and the discipline of not sending them

The failure is invisible: nobody files a bug saying "I stopped reading your
emails." Treat attention as a budget you spend, not a channel you fill.

| Tier | Trigger | Delivery | Budget |
|------|---------|----------|--------|
| **01 Interrupt** | P1 raised, SLA about to breach, incident, you're the last blocker | Push + SMS, ignores quiet hours, escalates through on-call ladder | A handful per **month** |
| **02 Attend** | Assigned, mentioned, review requested, your ticket blocked, escalation | In-app + one chosen channel, batched into user-set windows | A few per **day**, ranked |
| **03 Digest** | Everything else | Bundled into the daily brief, never sent alone | The default — alerts must argue their way *up* |

**Rules that keep the tiers honest**

- **Every alert is actionable** — approve / snooze / reassign / reply as buttons
  in the notification itself, on push, email and Slack alike.
- **Collapse by ticket, not by event** — six comments is one notification with a
  delta summary. Biggest volume reduction available.
- **Suppress what you caused** — no alerts for your own actions, or for a change
  on a ticket you're currently viewing.
- **Timezone + quiet hours are real** — only Tier 01 crosses, and crossings are logged.
- **Escalate on silence with a named ladder** — owner → on-call → lead, on a
  declared clock everyone can see beforehand.
- **Show people their own volume** — "340 received, 12 acted on" monthly, with
  one click to retune. Self-service tuning is what prevents mass muting.

---

## 8 · Email as a first-class surface

Half your users will never log in. For them, email **is** the product.

**Inbound.** A project address turns mail into tickets: threading by
`Message-ID` so replies land as comments on the right ticket, attachments
carried, signatures and quoted history stripped, sender matched to a contact,
duplicates merged. Replying to any notification posts an attributed comment.

**Outbound — four emails, deliberately:**

1. **Daily personal brief** (07:30 local) — your line, one decision per line.
2. **Weekly project brief** — stakeholder narrative, no jargon, no ticket IDs.
3. **On-event** — Tier 01 and 02 only.
4. **Monthly flow report** — cycle time, throughput, where the time went.

Nothing else has permission to send.

**Template rules**

- Subject line carries the decision ("You are the blocker on 1 thing · 2 ready to close").
- First three lines survive the mobile preview pane.
- Buttons act **from the inbox** via signed one-time links.
- Dark-mode safe; plain-text alternative always sent.
- Deep links land on the exact ticket with the reader's own delta already applied.

**The status page kills the status meeting.** Each project gets a shareable
read-only URL — current narrative, milestones, risks, what changed this week —
written by the Reporter, refreshed live. Send the link once; the recurring
meeting whose only purpose was reading a board aloud stops being scheduled.

---

## 9 · Metrics the product is judged on

| Metric | Definition | Why |
|--------|-----------|-----|
| Cycle time p50 / p85 | Ready → closed | The headline. p85 > p50 — the tail is where escalations live |
| Time in status | Per state, per ticket | Locates the wait; almost always "waiting for review/decision" |
| Flow efficiency | Active / total time | Typically 15–25%. Reframes "work faster" as "wait less" |
| First-response time | Created → first reply | What customer SLAs are written against |
| Reopen rate | Closed then reopened ≤30d | Guard against gaming cycle time |
| Aging WIP | Open tickets by age bucket | Leading indicator; cycle time is lagging |
| AI acceptance rate | Accepted / offered, per capability | Decides autonomy promotion; falling rate warns of drift |
| AI revert rate | Undone within 24h | The trust metric; must stay near zero past rung 3 |
| Hours returned | Meetings removed, drafts accepted, triage automated | The renewal argument, in the buyer's units |

---

## 10 · Trust, permissions, and what stops a sale

- **Inherits permissions, never exceeds them.** Real identity, real scopes. A
  summary carries the visibility of its least-visible source.
- **Everything revertible and logged.** Immutable audit log with inputs, cost,
  diff. Bulk revert by run, teammate, or time window. Exportable.
- **Labelled, always.** AI-authored content marked in UI, email, exports and API.
  A generated comment must never appear to come from a colleague.
- **Per-project opt-out and spend caps.** Regulated projects can run with the
  teammate off or pinned to rung 1. Hitting budget escalates, never silently degrades.
- **No training on customer data by default** — state it in the product, not just
  the DPA. Regional residency, per-workspace retention.
- **Confidence shown, not hidden.** Low-confidence output is hedged and routed to
  escalation. Being confidently wrong once costs more than ten summaries earn.

---

## 11 · Positioning

| Incumbent | Strength | The opening |
|-----------|----------|-------------|
| **Asana** | Cross-functional planning, non-technical adoption | No native link between a task and the commit/PR/deploy that resolves it. Signal-driven state is structurally hard for them |
| **Jira** | Depth, configurability, entrenchment | Configurability became the product; time-to-value is months of admin. Sensible defaults + speed is a real wedge |
| **Linear** | Speed, taste, keyboard-first craft | The bar you must meet on feel — but deliberately engineering-only and light on stakeholder reporting |
| **GitHub Issues** | Free, adjacent to code | No capacity, SLA, customer intake or cross-team reporting. Teams outgrow it around 30 people |

Defensible position = the intersection none of them occupy: **engineering-grade
signal fidelity + stakeholder-grade reporting + a teammate holding context across
both.** Lead with *"your tickets close faster, here's the chart"*; let
summarization and alerting be how you deliver it, not what you sell.

---

## 12 · Build order

Each phase independently useful. Resist starting with the teammate — an AI layer
over a weak object model produces exactly the unreliable summaries that poison
adoption.

1. **Earn the daily open.** Typed object model, four project views, Your Line,
   sub-100ms keyboard interaction, git/CI signal ingestion, tiered notifications.
   *No AI yet* — but every event typed and stored. Ship when the board is accurate
   without anyone dragging a card.
2. **The hook.** Standing brief, since-you-last-looked, closure records,
   provenance, freshness. Rungs 1–2 only. The phase that produces the demo people
   repeat.
3. **The wedge.** Auto-triage with duplicate detection, stall/SLA detection,
   inbound email-to-ticket, daily + weekly briefs, shareable status page. Cycle
   time starts visibly moving; non-users start touching the product.
4. **The moat.** Full autonomy dial with run records and revert, bounded
   implementation, capacity/Load view, flow analytics that prove ROI to the
   customer's finance team. By now their ticket history is a prior-art corpus no
   competitor can replicate — that's the switching cost.

---

## If you take only three things

1. **Type your events at write time** so summaries are cheap and correct.
2. **Ship "since you last looked"** before anything else AI-shaped.
3. **Never send a notification a person cannot act on from where they read it.**
