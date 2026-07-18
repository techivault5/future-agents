# The Project Success Blueprint
## Before, During, and After — The Complete Commitment Framework for Delivering at the Highest Level

---

## INTRODUCTION: WHY MOST PROJECTS FAIL

The Standish CHAOS Report (2023) shows that only 35% of software projects are completed on time, within budget, and to scope. The failure rate has barely moved in 30 years. The reason is not methodology. It is commitment architecture — the decisions, agreements, disciplines, and mindsets that leaders and teams apply before the first task begins.

**The 5 Root Causes of Project Failure:**
1. Unclear objectives and success criteria at the start
2. Inadequate stakeholder alignment and sponsorship
3. Scope creep unchecked by governance
4. Team and resource risks unidentified or ignored
5. No structured retrospection to learn from the work

This guide gives you the complete framework for each phase: **BEFORE**, **DURING**, and **AFTER**.

---

## PART 1: THE PROJECT COMMITMENT HIERARCHY

Before any methodology, understand this hierarchy. Projects fail at the base, not the peak.

```
                    ┌─────────────────────┐
                    │   DELIVERY MASTERY  │ ← Methods, tools, cadences
                    │    (techniques)     │
                    ├─────────────────────┤
                    │   TEAM ALIGNMENT    │ ← Trust, communication, conflict
                    │    (relationships)  │
                    ├─────────────────────┤
                    │  STAKEHOLDER TRUST  │ ← Sponsorship, governance, decision rights
                    │   (sponsorship)     │
                    ├─────────────────────┤
                    │  PURPOSE CLARITY    │ ← WHY this project, what does success look like
                    │    (foundation)     │
                    └─────────────────────┘
```

Most project management methodologies address only the top level. The most important work happens at the bottom.

---

## PART 2: BEFORE THE PROJECT — THE FOUNDATION PHASE

### 2.1 The Project Charter

The charter is the contract between the project and the organisation. Nothing should start without one.

**Charter Components:**

| Section | What to Define | Anti-Pattern |
|---|---|---|
| **Problem Statement** | Why does this project exist? What problem does it solve? | "We're doing this because of Q3 planning" |
| **Business Case** | What value will this create? ROI, cost savings, risk reduction? | No quantified value |
| **Success Criteria** | What does "done" look like, specifically and measurably? | "Improved customer experience" |
| **Scope** | What is IN. What is OUT. Both are equally important. | Only defining what's in |
| **Constraints** | Budget, time, resource limits | Ignoring constraints until they bite |
| **Assumptions** | What are we treating as true? (must be validated) | Not surfacing assumptions |
| **Risks** | What could prevent success? | Risk section left blank |
| **Stakeholders** | Who is affected? Who must decide? Who must be informed? | Partial list |
| **Executive Sponsor** | Named, committed, available — not ceremonial | Sponsor in name only |

**The 5-Why Test for Project Purpose:**
Ask "Why?" five times about the stated objective. The answer at Why 5 is the actual business need. Design the project to serve that, not the surface request.

---

### 2.2 Success Criteria — The Most Neglected Step

Without measurable success criteria, every project succeeds (by its own definition) and no one knows what was actually delivered.

**The SMART+ Success Criteria Framework:**

| Element | Definition | Example |
|---|---|---|
| **Specific** | Exactly what will change | "Reduce invoice processing time" |
| **Measurable** | With numbers | "...from 5 days to 1 day" |
| **Achievable** | Within realistic capacity | "...by optimising existing systems (not rebuilding)" |
| **Relevant** | Tied to a business outcome | "...reducing working capital tied in AP" |
| **Time-bound** | By when | "...by Q2 end" |
| **+ Agreed** | All stakeholders sign off | Sponsor, owner, team confirm alignment |

**The Acceptance Criteria Checklist:**
- [ ] Can we measure this before the project and after?
- [ ] Will every stakeholder agree that this metric means success?
- [ ] Is this within the project's control to influence?
- [ ] Is there a baseline established for comparison?

---

### 2.3 Stakeholder Mapping and Alignment

**The Power-Interest Matrix:**

```
HIGH POWER
    ↑
    │  Manage Closely     │  Keep Satisfied
    │  (Key Players)      │  (Meet Needs)
    │  Engage deeply,     │  High-level engagement,
    │  co-create          │  avoid overwhelming
    ├─────────────────────┼────────────────────
    │  Monitor            │  Keep Informed
    │  (Low Priority)     │  (Show Value)
    │  Minimal effort     │  Regular but light
    │                     │  touch
    └─────────────────────┴────────────────────→ HIGH INTEREST
```

**The Stakeholder Commitment Curve:**
Move stakeholders along this curve deliberately:

```
Unaware → Aware → Interested → Supportive → Committed → Championing
```

**For each key stakeholder, define:**
- Current position on the curve
- Required position for project success
- Specific actions to close the gap

**Stakeholder Analysis Template:**

| Stakeholder | Role | Current Position | Required Position | Key Concern | Engagement Strategy |
|---|---|---|---|---|---|
| [Name] | [Sponsor] | Aware | Committed | Budget certainty | Monthly 1:1 with ROI update |
| [Name] | [End User Lead] | Unaware | Supportive | Change disruption | Include in design workshops |

---

### 2.4 Risk Assessment — The Pre-Mortem Technique

Developed by psychologist Gary Klein, the **Pre-Mortem** is the most powerful risk tool available.

**How to run a Pre-Mortem:**
1. Gather the project team and key stakeholders
2. State: "Imagine it is 12 months from now. The project has failed catastrophically. What happened?"
3. Every person writes silently for 5 minutes — list every possible cause of failure
4. Share and categorise: Technical, Resource, Scope, Stakeholder, External
5. For each high-severity risk: define likelihood, impact, mitigation, owner

**Risk Register Format:**

| Risk | Category | Likelihood (H/M/L) | Impact (H/M/L) | Risk Score | Mitigation | Owner | Trigger |
|---|---|---|---|---|---|---|---|
| Key technical lead leaves | Resource | M | H | High | Cross-train second lead, document architecture | PM | Any resignation |
| Scope expands 30%+ | Scope | H | H | Critical | Change control process, sponsor authority for scope decisions | Sponsor | Any undocumented scope request |

**The Assumption Register:**
Every project runs on assumptions. Surface them:

| Assumption | Criticality | How to validate | Validation deadline |
|---|---|---|---|
| Legal review takes 2 weeks | High | Confirm with Legal lead | Week 1 |
| Integration API is available | Critical | Technical spike in Week 1 | Week 1 |

---

### 2.5 Team Setup and Operating Model

**The Team Contract:**
A team contract is a one-page agreement on how the team will work together.

```
TEAM CONTRACT — [Project Name]

PURPOSE: Why we're here and what we're building

HOW WE MAKE DECISIONS:
  - Day-to-day operational: [PM / Tech Lead decides]
  - Scope or priority changes: [PM + Sponsor]
  - Technical architecture: [Tech Lead + Architect]
  - Budget >$50K: [Sponsor only]

HOW WE COMMUNICATE:
  - Async updates: Slack #project-name
  - Urgent: Call or DM — no emails for urgent
  - Status to stakeholders: PM, every Friday
  - Escalation path: PM → Sponsor → Steering Committee

HOW WE HANDLE CONFLICT:
  - Raise within 24 hours
  - First: directly between the parties
  - Then: to PM if unresolved in 48 hours
  - We assume positive intent unless demonstrated otherwise

WORKING NORMS:
  - Meetings: agenda 24 hours prior or we decline
  - Response time: Slack within 4 hours in core hours
  - Core hours: 9am–4pm [timezone]
  - We protect focus time: no meetings [Wed PM]

COMMITMENTS:
  - We show up prepared
  - We surface blockers immediately, not at sprint end
  - We raise the flag before we miss a commitment
```

**Team Roles Clarity (RACI):**

| Activity | PM | Tech Lead | Developer | QA | Sponsor |
|---|---|---|---|---|---|
| Architecture decisions | C | A | R | I | I |
| Scope change approval | R | C | I | I | A |
| Stakeholder communication | A/R | C | I | I | I |
| Sprint planning | A | R | R | R | I |
| Go/no-go decision | R | R | C | C | A |

*R=Responsible, A=Accountable, C=Consulted, I=Informed*

---

### 2.6 The BEFORE Commitment Checklist

Use this checklist before any project begins. If more than 3 items are unchecked, the project is not ready to start.

**Clarity:**
- [ ] Problem statement is documented and agreed by all stakeholders
- [ ] Success criteria are measurable and signed off
- [ ] Scope is defined — IN and OUT both documented
- [ ] Assumptions are listed and have validation plans

**Alignment:**
- [ ] Executive sponsor is named, committed, and available
- [ ] All key stakeholders are mapped with engagement plans
- [ ] Decision rights are documented and agreed
- [ ] Team contract is signed

**Resourcing:**
- [ ] Team is confirmed with confirmed availability percentages
- [ ] Budget is approved or the approval path is clear
- [ ] Critical dependencies on external teams are documented and committed
- [ ] Key risks are in the risk register with owners

**Planning:**
- [ ] High-level milestones and phase gates are defined
- [ ] Definition of Done is established for each phase
- [ ] Reporting and governance cadences are set

---

## PART 3: DURING THE PROJECT — EXECUTION EXCELLENCE

### 3.1 The Execution Operating System

**The Weekly Rhythm:**

| Cadence | Participants | Purpose | Duration | Output |
|---|---|---|---|---|
| Daily standup | Team | Synchronise, surface blockers | 15 min | Blockers visible, resolved same day |
| Sprint planning (2 weekly) | Team + PM | Commit to sprint backlog | 2 hours | Sprint backlog, capacity confirmed |
| Sprint review | Team + Stakeholders | Demo progress, get feedback | 1 hour | Feedback list, acceptance confirmation |
| Sprint retrospective | Team | Improve how we work | 1 hour | Action items for next sprint |
| Stakeholder update | PM + Sponsor | Status, decisions, risks | 30 min | Decision log updated |
| Risk review | PM + Tech Lead | Review risk register | 30 min | Risks updated, new risks added |

### 3.2 The Standup Protocol

**The 3 Questions:**
1. What did I complete since last standup?
2. What will I complete by next standup?
3. What is blocking me?

**Anti-Patterns:**
- Reporting to the PM instead of the team
- Problem-solving in the standup (take it to a separate call)
- "I'm just working on..." (no completions or blockers named)
- Attendance optional — the standup is the team's minimum operating commitment

### 3.3 Scope Management

**The Change Control Process:**

```
Scope change requested
        ↓
PM documents: What, Why, Impact on time/cost/quality
        ↓
Impact assessment (PM + Tech Lead)
        ↓
Decision by Sponsor (if major) or PM (if minor — pre-agreed threshold)
        ↓
Accepted: Add to backlog, reprioritise → Rejected: Record decision, communicate
```

**The Scope Creep Warning Signs:**
- "While we're in there, can we just..."
- "It's only a small change"
- "That was always in scope" (but it's not in the charter)
- Teams working on undocumented features
- Sprint velocities declining without explained cause

**The Governance Ladder:**

| Change Type | Authority | Process |
|---|---|---|
| Minor (< 3 days of effort, no milestone impact) | PM | Document, inform sponsor |
| Medium (3–10 days, may impact milestone) | PM + Sponsor alignment | Change request, decision within 48 hours |
| Major (> 10 days, milestone or budget impact) | Steering committee | Formal change request, scheduled agenda item |

### 3.4 Status Reporting — The RAG Framework

**Red-Amber-Green (RAG) Status Definitions:**

| Colour | Meaning | Required Action |
|---|---|---|
| **GREEN** | On track — no material risks to scope, time, or cost | Continue; update stakeholders |
| **AMBER** | Risk identified — without intervention, will become RED | PM leads mitigation; sponsor informed; options presented |
| **RED** | Off track — scope, time, or cost impacted | Immediate sponsor involvement; recovery plan required within 5 days |

**The Status Report Template (One Page):**

```
PROJECT STATUS — [Name] — Week [N] — [Date]

OVERALL STATUS: ██ GREEN / ██ AMBER / ██ RED

MILESTONE STATUS:
[Milestone]    [Target Date]    [Status]    [Notes]

KEY ACCOMPLISHMENTS THIS WEEK:
• 

IN PROGRESS:
• 

KEY DECISIONS NEEDED:
• [Decision] — Owner: [Name] — By: [Date]

RISKS AND ISSUES:
[Risk/Issue]    [Severity]    [Mitigation]    [Owner]

NEXT WEEK FOCUS:
• 
```

### 3.5 Managing Team Performance During Execution

**The High-Performance Team Model (Tuckman):**

| Stage | Signs | PM Action |
|---|---|---|
| **Forming** | Politeness, low productivity, role confusion | Establish norms, clarify roles, build trust |
| **Storming** | Conflict, power struggles, low morale | Don't suppress conflict — name it, facilitate resolution |
| **Norming** | Agreement on processes, improving cohesion | Reinforce positive patterns, recognise wins |
| **Performing** | High output, autonomous decisions, trust | Protect the environment, minimise interruptions |
| **Adjourning** | Winding down, risk of disengagement | Recognise contribution, plan transition well |

**Energy Management on Long Projects:**
- Celebrate small wins at every sprint review — never skip recognition
- Sprint retrospectives are not optional — they prevent "team debt"
- Protect the team from unnecessary meetings — a PM's job is to be a shield, not a funnel
- Address underperformance immediately — one underperformer lowers the whole team's standards

### 3.6 Issue Management

**Issue vs. Risk:**
- A **risk** is something that might happen
- An **issue** is something that has happened and needs resolution

**Issue Resolution Framework:**

```
Issue raised (any team member, any time)
        ↓
Captured in issue log with: description, impact, priority, owner
        ↓
Owner investigates within 24 hours (P1), 48 hours (P2), 5 days (P3)
        ↓
Resolution options presented to PM (and Sponsor if needed)
        ↓
Decision made, resolution actioned, issue closed
        ↓
Lessons captured if systemic
```

**Issue Priority Levels:**

| Priority | Definition | Response Time |
|---|---|---|
| **P1 — Critical** | Blocking delivery, team cannot proceed | Same day resolution or escalation |
| **P2 — High** | Significant risk to milestone; workaround exists but costly | 48 hours |
| **P3 — Medium** | Manageable; can be resolved in current sprint | 5 days |

---

## PART 4: AFTER THE PROJECT — CLOSING WITH EXCELLENCE

Most teams skip the close phase. This is where the organisation's learning lives.

### 4.1 The After-Action Review (AAR)

The AAR was developed by the US Army and adapted by organisations including Google, Amazon, and elite military units. It is the gold standard for post-project learning.

**The 4 AAR Questions:**
1. **What was intended to happen?** (The plan)
2. **What actually happened?** (The reality)
3. **Why was there a difference?** (The analysis)
4. **What will we do differently next time?** (The learning)

**AAR Facilitation Principles:**
- No blame, no defensiveness — focus on the system and process, not the person
- Every voice has equal weight in an AAR — the most junior person may have the most important insight
- Focus on systemic causes, not individual failures
- Document and distribute — an AAR that stays in a meeting room is useless

**The AAR Template:**

```
AFTER-ACTION REVIEW — [Project Name]
Date: | Facilitator: | Participants:

PROJECT SUMMARY:
Objective: | Outcome: | Duration: | Budget vs Actual:

WHAT WENT WELL (Keep Doing):
• [Practice] — [Why it worked] — [How to embed]

WHAT DIDN'T GO WELL (Stop Doing or Fix):
• [Issue] — [Root cause] — [What we'd do differently]

KEY LESSONS LEARNED:
• 

RECOMMENDATIONS FOR FUTURE PROJECTS:
• [Recommendation] — [Who owns it] — [Timeline]

KNOWLEDGE ARTIFACTS TO CREATE/UPDATE:
• [Runbook, template, process doc] — [Owner] — [Date]
```

### 4.2 Knowledge Transfer and Documentation

**The Knowledge Triangle:**

```
        TACIT KNOWLEDGE
        (in people's heads)
              ↓
       EXPLICIT KNOWLEDGE
       (written, documented)
              ↓
        REUSABLE ASSET
     (template, playbook, system)
```

**Project Close Documentation Checklist:**
- [ ] Final project report (actuals vs plan)
- [ ] Architecture decision records (ADRs) updated
- [ ] Runbooks for operational processes documented
- [ ] Known issues and workarounds documented in support system
- [ ] Process improvements captured in team wiki
- [ ] Dependencies and integrations documented
- [ ] Test cases and results archived
- [ ] Training materials completed and handed over

### 4.3 Measuring Project Success — Beyond On-Time On-Budget

On-time, on-budget delivery is a lagging indicator. These leading indicators tell you whether the project actually succeeded:

**Business Outcome Metrics (measured 30/60/90 days post-launch):**
- Did the project solve the problem it was designed to solve?
- Are the metrics in the success criteria moving?
- Has user adoption met the target?
- Are operational teams self-sufficient (not dependent on the project team)?

**Team Health Metrics:**
- Are team members proud of what they built?
- Were the working norms maintained throughout?
- Would team members volunteer to work together again?

**Organisational Learning Metrics:**
- Have lessons been incorporated into the next project?
- Have templates and processes been updated?
- Has knowledge been distributed beyond the core team?

### 4.4 Transition and Handover

**The Handover Protocol:**

```
HANDOVER CHECKLIST — [Project Name]

OPERATIONS:
□ Operations team trained and signed off
□ Support runbook reviewed and approved
□ Escalation path documented and tested
□ Monitoring and alerting configured and tested
□ On-call rotation established

BUSINESS:
□ Business owner trained on new process/system
□ Communication to all affected end users sent
□ Feedback mechanism established
□ 30-day post-launch review scheduled

TECHNICAL:
□ Code reviewed and merged to main
□ Infrastructure documented
□ Credentials transferred to operations
□ Access provisioned/deprovisioned correctly
□ Disaster recovery plan documented and tested

GOVERNANCE:
□ Final project report submitted
□ Budget closure confirmed
□ Contracts closed
□ Vendor relationships transitioned
```

### 4.5 The AFTER Commitment Checklist

- [ ] AAR conducted within 2 weeks of project completion
- [ ] Lessons learned documented and shared
- [ ] Reusable assets created (templates, runbooks, playbooks)
- [ ] Business outcomes measurement scheduled for 30/60/90 days
- [ ] Handover documentation complete and signed off
- [ ] Team recognised and contributions celebrated
- [ ] Final project report submitted to sponsor and stakeholders
- [ ] Knowledge management updated

---

## PART 5: PROJECT METHODOLOGY INTEGRATION

### 5.1 Choosing Your Methodology

| Methodology | Best For | Key Principles | Avoid When |
|---|---|---|---|
| **Agile/Scrum** | Evolving requirements, software products | Iterative delivery, inspect-and-adapt, team autonomy | Hard fixed regulatory deadlines |
| **PRINCE2** | Large, complex, high-governance projects | Business case, stage gates, controlled change | Small teams, fast-moving environments |
| **PMI/PMBOK** | Traditional projects with defined scope | Process-based, certification framework | High ambiguity environments |
| **Kanban** | Operations, support, continuous flow | Visualise flow, limit WIP, pull system | Projects needing structured sprints |
| **SAFe (Scaled Agile)** | Large enterprise with multiple teams | PI Planning, Agile Release Trains | Small teams (overcomplicated) |
| **Lean** | Reducing waste, optimising processes | Value stream, eliminate waste, continuous improvement | One-time novel projects |

### 5.2 Hybrid Delivery Model

Most real-world projects benefit from a hybrid approach:

**Phase 1 — Discovery (Agile):** Iterative, exploratory, hypothesis-driven
**Phase 2 — Build (Scrum):** Sprint-based, demo-driven, adaptable
**Phase 3 — Deploy (Waterfall-lean):** Structured, risk-managed, governance-heavy
**Phase 4 — Operate (Kanban):** Flow-based, continuous improvement

### 5.3 OKRs in Project Management

OKRs (Objectives and Key Results) provide the strategic frame for project prioritisation.

**Project-Level OKR Template:**

```
OBJECTIVE: [Ambitious, qualitative goal]
KEY RESULTS:
  KR1: [Measurable outcome] — Baseline: [X] → Target: [Y]
  KR2: [Measurable outcome] — Baseline: [X] → Target: [Y]
  KR3: [Measurable outcome] — Baseline: [X] → Target: [Y]

CONNECTION TO COMPANY OKR: [Which company-level KR does this serve?]
```

**OKR Health Checks (monthly):**
- Are we progressing on the key results?
- Has anything changed that makes this OKR less relevant?
- Are teams aligned on priority relative to other OKRs?

---

## PART 6: TOP LEADER INSIGHTS ON PROJECT DELIVERY

### Jeff Bezos — Working Backwards
Amazon's product and project process starts at the outcome, not the solution:
1. Write the press release for the completed project (what will it say?)
2. Write the FAQ for the press release
3. Build backwards from the outcome to the first step

**Applied:** Before starting any project, write the "launch press release" — what headline would a journalist write? This ensures the team is building towards a real outcome, not just completing activities.

### Elon Musk — The 5-Step Engineering Process
Applied at Tesla, SpaceX, and Boring Company:
1. **Question the requirement** — "All requirements are dumb until proven smart"
2. **Delete unnecessary steps, parts, or processes** — if you're not adding things back, you didn't delete enough
3. **Simplify and optimise** — only after deleting
4. **Accelerate cycle time** — speed up delivery of what remains
5. **Automate** — only after the first 4 steps

**Warning:** Many projects fail because teams automate bad processes. Musk's rule: don't automate until you've done steps 1–4.

### Ray Dalio — Radical Transparency in Delivery
- Make problems visible, not invisible. The team that hides issues until sprint demo is failing.
- Create a culture where raising a blocker is celebrated, not penalised
- Use "believability-weighted" decision-making — value input from those with the most relevant experience

### Satya Nadella — Growth Mindset in Project Failure
When projects hit problems (they always do):
- Frame setbacks as learning, not failure
- Ask: "What did this teach us?" before "Who is responsible?"
- Ensure the team has psychological safety to report bad news early

### Jensen Huang — Embrace the Difficulty
"The more painful the suffering, the more you learn." Applied to project delivery:
- Don't protect the team from hard realities — bring them into the problem-solving
- Expect discomfort and treat it as signal that important work is happening
- Build a team identity around resilience, not comfort

---

## PART 7: PROJECT LEADERSHIP SELF-ASSESSMENT

Rate yourself 1–10:

| Competency | 1–3 | 4–6 | 7–10 | My Score |
|---|---|---|---|---|
| **Charter quality** | No formal charter | Charter exists, some gaps | SMART criteria, full stakeholder sign-off | |
| **Stakeholder management** | Reactive | Regular updates | Power-interest mapped, proactive engagement | |
| **Risk management** | Unknown risks | Risk log exists | Pre-mortem, regular reviews, owned mitigations | |
| **Scope management** | Constant scope creep | Change process exists | Zero undocumented scope, change log maintained | |
| **Team health** | High friction, low trust | Functional, some tension | High trust, conflict resolved quickly | |
| **Status communication** | Reactive/ad hoc | Regular updates | RAG, BLUF, decision-ready briefs | |
| **Post-project learning** | No retrospection | Lessons learned sometimes | AAR, knowledge assets, embedded improvements | |
| **Business outcome focus** | Delivery metrics only | Tracks some outcomes | 30/60/90 day business metric reviews | |

---

*"A project is not a task. It is a commitment — a promise made to an organisation, a team, and a set of customers or stakeholders. The best project leaders understand that commitment has three chapters: what you promise before you begin, how you honour that promise while working, and what you leave behind when you're done."*
