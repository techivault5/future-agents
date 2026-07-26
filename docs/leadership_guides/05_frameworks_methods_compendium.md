# The Frameworks, Methods & Processes Compendium
## The Complete Reference for High-Performance Thinking, Delivery, and Leadership

---

## INTRODUCTION: WHY FRAMEWORKS MATTER

A framework is a structured way of thinking that allows you to apply proven logic to new situations. It is not a rigid template — it is a scaffold that gives your thinking shape.

The leaders and organisations at the top of performance invest heavily in shared frameworks because:
- They create a common language that accelerates decision-making
- They reduce cognitive load on well-understood problems, reserving mental energy for novel ones
- They encode the lessons of experience into replicable patterns
- They prevent expert-beginner gap — good frameworks make junior practitioners more effective faster

This compendium organises every major framework referenced in elite leadership and delivery into categories. For each framework: what it is, when to use it, how to apply it, and the insight from top practitioners.

---

## SECTION 1: GOAL-SETTING FRAMEWORKS

### 1.1 OKRs — Objectives and Key Results

**Origin:** Andy Grove at Intel; popularised by John Doerr at Google

**What it is:** A goal-setting framework that separates the qualitative objective (where do we want to go?) from the quantitative key results (how do we know we got there?).

**Structure:**
```
OBJECTIVE: [Inspiring, qualitative, time-bound goal]
  Key Result 1: [Measurable outcome — not task — with baseline and target]
  Key Result 2: [Measurable outcome]
  Key Result 3: [Measurable outcome]
```

**Rules:**
- Objectives should be ambitious — 70% achievement is considered excellent
- Key Results are outcomes, not activities ("NPS increases from 42 to 55" not "Run NPS survey")
- 3–5 OKRs per level; 3–5 KRs per objective
- Set quarterly for teams; annually for organisation
- OKRs cascade: Company → Team → Individual alignment

**When to use:** Quarterly planning, team alignment, performance management

**Pitfall:** Sandbagging (setting low targets to guarantee achievement), treating KRs as task lists

---

### 1.2 SMART Goals

**Origin:** George T. Doran (1981)

| Letter | Meaning | Test Question |
|---|---|---|
| **S** — Specific | Precisely defined | What exactly will we accomplish? |
| **M** — Measurable | Quantifiable | How will we know we've succeeded? |
| **A** — Achievable | Realistic given constraints | Is this possible with our resources? |
| **R** — Relevant | Aligned to strategic priority | Does this matter to the business? |
| **T** — Time-bound | Has a clear deadline | By when will this be complete? |

**When to use:** Individual goal setting, project success criteria, performance objectives

**Advanced version:** SMARTER (+ Evaluated and Reviewed)

---

### 1.3 The 12-Week Year

**Origin:** Brian Moran and Michael Lennington

**What it is:** Treats each 12-week period as a full "year" — with the goal-setting intensity and urgency of annual planning compressed into quarterly cycles.

**Premise:** The annual planning cycle creates complacency ("I have until December"). Compressing to 12 weeks creates urgency at all times.

**12-Week Year Structure:**
1. Define your vision (long-term direction)
2. Set 12-week goals (3–5 maximum)
3. Create a 12-week execution plan (weekly actions)
4. Execute with a weekly scorecard
5. Review and recalibrate weekly

**Weekly Scorecard:**
- Rate each planned activity as complete or not complete
- Target: 85%+ execution rate correlates with achieving goals
- Review what blocked the 15%; address systemically

**When to use:** Personal productivity, team execution cadence, quarterly sprints

---

## SECTION 2: PRIORITISATION FRAMEWORKS

### 2.1 The Eisenhower Matrix (Urgent-Important Matrix)

**Origin:** Dwight D. Eisenhower; popularised by Stephen Covey in *7 Habits*

```
                    URGENT                    NOT URGENT
            ┌─────────────────────┬─────────────────────┐
IMPORTANT   │  QUADRANT 1         │  QUADRANT 2          │
            │  Do First           │  Schedule            │
            │  (Crises, deadlines,│  (Planning, learning,│
            │   emergencies)      │   relationship build)│
            ├─────────────────────┼─────────────────────┤
NOT         │  QUADRANT 3         │  QUADRANT 4          │
IMPORTANT   │  Delegate           │  Eliminate           │
            │  (Most meetings,    │  (Scrolling, trivial │
            │   some emails,      │   tasks, low-value   │
            │   interruptions)    │   habits)            │
            └─────────────────────┴─────────────────────┘
```

**The Key Insight:** High performers spend most time in Q2. Most people spend most time in Q1 and Q3. Q2 time is the only time that prevents Q1 crises.

**When to use:** Daily task management, workload assessment, team prioritisation

---

### 2.2 MoSCoW Prioritisation

**Origin:** Dai Clegg at Oracle; standard in DSDM Agile

| Priority | Meaning | Test |
|---|---|---|
| **Must Have** | Non-negotiable; project fails without it | Would we cancel the launch if this was missing? |
| **Should Have** | Important but not critical | Significant pain if missing, but workable |
| **Could Have** | Nice to have | Small improvement; include if time/cost allows |
| **Won't Have (this time)** | Out of scope for now; future consideration | Agreed exclusion — prevents scope creep |

**Rule of thumb:** Must Haves should not exceed 60% of total effort

**When to use:** Sprint planning, MVP definition, scope conversations with stakeholders

---

### 2.3 The 80/20 Rule (Pareto Principle)

**Origin:** Vilfredo Pareto; popularised by Richard Koch in *The 80/20 Principle*

**The Insight:** 80% of results come from 20% of causes. This holds across domains:
- 20% of customers → 80% of revenue
- 20% of bugs → 80% of crashes
- 20% of features → 80% of user value
- 20% of your work → 80% of your impact

**How to use:**
1. List all activities/causes
2. Estimate contribution to the outcome
3. Identify the top 20%
4. Disproportionately invest in those; reduce or eliminate the rest

**When to use:** Resource allocation, product roadmap prioritisation, personal productivity

---

### 2.4 The ICE Scoring Model

**Origin:** Sean Ellis (Growth hacking)

| Factor | Question | Score (1–10) |
|---|---|---|
| **I** — Impact | How much will this move the metric if it works? | |
| **C** — Confidence | How confident are we this will work? | |
| **E** — Ease | How easy is this to implement? | |
| **ICE Score** | Average of I × C × E | Higher = higher priority |

**When to use:** Feature prioritisation, growth experiment backlog, marketing campaign selection

---

## SECTION 3: PROBLEM-SOLVING FRAMEWORKS

### 3.1 The 5 Whys

**Origin:** Sakichi Toyoda; standard in Toyota Production System

**What it is:** Asking "Why?" iteratively (typically 5 times) to trace a problem to its root cause.

**Example:**
```
PROBLEM: The server is down
Why? → The disk is full
Why? → Log files weren't being rotated
Why? → Log rotation wasn't configured
Why? → The deployment runbook didn't include log rotation
Why? → We don't have a standard runbook template that includes it
ROOT CAUSE: Absence of a standard runbook template
```

**Rules:**
- Each "why" must address the actual answer given, not a generalisation
- Avoid "human error" as a root cause — it is never the root; ask why the error was possible
- Multiple causal chains may emerge — follow all of them
- Stop when you reach a systemic cause within your control

**When to use:** Post-incident reviews, retrospectives, quality failures, recurring issues

---

### 3.2 The Fishbone Diagram (Ishikawa / Cause-and-Effect)

**Origin:** Kaoru Ishikawa

**What it is:** A visual tool for categorising potential causes of a problem.

**Structure:**
```
                                                         ┌─────────┐
People ────────────────────────────────────────────────► │         │
                                                         │ PROBLEM │
Process ───────────────────────────────────────────────► │         │
                                                         │         │
Technology ────────────────────────────────────────────► │         │
                                                         │         │
Environment ───────────────────────────────────────────► └─────────┘
```

**Categories (The 6 M's for manufacturing):** Machine, Method, Material, Man, Measurement, Mother Nature

**For service/knowledge work:** People, Process, Technology, Policy, Environment, Data

**When to use:** Root cause analysis, problem workshops, quality reviews

---

### 3.3 PDCA — Plan-Do-Check-Act (The Deming Cycle)

**Origin:** W. Edwards Deming

**The Cycle:**
```
        PLAN
    (Define the problem,
     design the solution)
         ↓
    ACT                    DO
(Standardise if         (Implement
 successful;            the solution
 re-plan if not)        at small scale)
         ↑                    ↓
            CHECK
        (Measure results
         vs. expectations)
```

**When to use:** Continuous improvement, quality management, iterative problem solving, change implementation

---

### 3.4 Design Thinking (5-Stage)

**Origin:** IDEO; Stanford d.school

**The 5 Stages:**

| Stage | Activity | Output |
|---|---|---|
| **1. Empathise** | Deep user research — observe, interview, experience | Empathy map, user insights |
| **2. Define** | Synthesise findings into a problem statement | "How Might We" (HMW) statements |
| **3. Ideate** | Generate solutions without judgment | 100+ ideas, diverge before converging |
| **4. Prototype** | Build low-fidelity representations quickly | Paper prototypes, wireframes, storyboards |
| **5. Test** | Get feedback from real users early | Learning, iteration, refinement |

**Design Thinking Mindsets:**
- Bias toward action (build before perfect)
- Radical collaboration (diversity of perspective)
- Show don't tell (prototype, visualise)
- Focus on human values (what matters to the user)
- Embrace experimentation (fail fast, learn fast)

**When to use:** New product development, service design, solving wicked problems, UX research

---

### 3.5 The Cynefin Framework

**Origin:** Dave Snowden (IBM, 1999)

**What it is:** A sense-making framework for categorising problems by the nature of their cause-and-effect relationships.

```
COMPLICATED                          COMPLEX
(Experts)                           (Emergent)
"Sense → Analyse → Respond"         "Probe → Sense → Respond"
Best practice of experts            Run experiments; amplify what works
e.g., Surgery, Engineering          e.g., Strategy, Org design

         ┌──────────────────────────┐
         │         DISORDER         │
         │  (Unclear which applies) │
         └──────────────────────────┘

OBVIOUS / CLEAR                      CHAOTIC
(Established)                        (Act First)
"Sense → Categorise → Respond"       "Act → Sense → Respond"
Apply known best practice            Stabilise first, then sense
e.g., Password reset, invoicing      e.g., Crisis, acute failure
```

**How to use:**
- Categorise your problem domain
- Apply the appropriate management approach
- Don't apply complex-domain management (experiments) to obvious-domain problems (follow the process)
- Don't apply obvious-domain management (best practice) to complex-domain problems (it won't work)

**When to use:** Strategy formulation, change management, incident response, innovation decisions

---

### 3.6 Pre-Mortem Analysis

**Origin:** Gary Klein (psychologist)

**What it is:** A prospective failure analysis — imagine the project has already failed, then explain why.

**How to run:**
1. Gather the team before the project starts (or at a major decision point)
2. Premise: "It is [date]. The project has failed completely. Write down every reason it failed."
3. 5 minutes silent individual writing
4. Round-robin sharing; capture all items
5. Categorise: Technical, Resource, Scope, Stakeholder, External, Process
6. For each high-severity item: define mitigation, owner, trigger

**Why it works:**
- Overcomes optimism bias and groupthink
- Surfaces risks that individuals are reluctant to voice directly
- Creates psychological safety for bad news because it's framed as fiction
- Produces a better risk register than "what could go wrong?" asked directly

**When to use:** Before any significant project, major change, launch, or investment

---

## SECTION 4: COMMUNICATION AND THINKING FRAMEWORKS

### 4.1 The Pyramid Principle

**Origin:** Barbara Minto (McKinsey, 1970s)

**The Core Rule:** Answer first, support second. Your conclusion comes before your evidence.

**Structure:**
```
ANSWER / RECOMMENDATION (Top of pyramid)
    ├── Argument 1
    │       ├── Evidence
    │       └── Evidence
    ├── Argument 2
    │       ├── Evidence
    │       └── Evidence
    └── Argument 3
            ├── Evidence
            └── Evidence
```

**The MECE Principle:** Arguments must be Mutually Exclusive (no overlap) and Collectively Exhaustive (no gaps).

**When to use:** Writing any document, email, or presentation where you need to persuade or inform a busy audience

---

### 4.2 SCQA — Situation, Complication, Question, Answer

**Origin:** Barbara Minto

**What it is:** A story structure for professional communication that establishes context before proposing a recommendation.

| Component | Purpose | Length |
|---|---|---|
| **Situation** | Shared context the audience already accepts as true | 1–2 sentences |
| **Complication** | The change, tension, or problem that disturbs the situation | 1–2 sentences |
| **Question** | The question the complication raises — what must be answered? | 1 sentence |
| **Answer** | Your recommendation or conclusion | 1–3 sentences |

**When to use:** Opening any document, presentation, or executive conversation

---

### 4.3 Mental Models — The Munger Lattice

**Origin:** Charlie Munger

**What it is:** A collection of key thinking models from multiple disciplines used together to reason about any problem.

**The Essential Mental Models:**

| Model | Discipline | What it teaches |
|---|---|---|
| **First Principles** | Physics / Philosophy | Strip assumptions; reason from fundamental truths |
| **Inversion** | Mathematics | Ask "how do we fail?" and avoid those things |
| **Opportunity Cost** | Economics | Every choice has a cost — what are you giving up? |
| **Compounding** | Mathematics/Finance | Small consistent improvements have enormous long-term effects |
| **Circle of Competence** | Strategy | Know what you know; know what you don't; operate accordingly |
| **Margin of Safety** | Engineering / Finance | Build in buffers; don't run systems at capacity |
| **Regression to the Mean** | Statistics | Extremes tend to normalise; don't over-react to outliers |
| **Availability Heuristic** | Psychology | Recent and memorable events are over-weighted in decisions |
| **Confirmation Bias** | Psychology | We seek evidence that confirms existing beliefs |
| **Incentive-caused Bias** | Psychology | Show me the incentives and I'll show you the outcome |

**When to use:** Any complex decision, diagnosis, strategy formulation

---

### 4.4 The Feynman Technique

**Origin:** Richard Feynman (Nobel Prize physicist)

**4 Steps:**
1. **Choose the concept** you want to understand
2. **Teach it in plain language** as if to a child — no jargon
3. **Identify gaps** — where did you stumble? Those are your knowledge gaps
4. **Review and simplify** — go back to source material for gaps; then re-explain more simply

**The Test:** Can you explain it without using the technical vocabulary of the field? If not, you don't understand it fully — you've memorised it.

**Feynman:** "If you can't explain it simply, you don't understand it well enough."

**When to use:** Learning new domains, preparing to explain complex concepts to others, knowledge assessment

---

## SECTION 5: LEARNING AND PERFORMANCE FRAMEWORKS

### 5.1 The DiSSS Framework (Tim Ferriss)

**Origin:** Tim Ferriss (*The 4-Hour Chef*)

| Letter | Step | Question |
|---|---|---|
| **D** — Deconstruct | Break the skill into its smallest learnable components | What are the minimum learnable units? |
| **S** — Selection | Identify the 20% that produces 80% of results | What are the highest-leverage sub-skills? |
| **S** — Sequencing | Order the learning for maximum retention | What must be learned before what? |
| **S** — Stakes | Add consequences that enforce practice | What makes not practising painful? |

**When to use:** Skill acquisition, curriculum design, self-directed learning plans

---

### 5.2 Spaced Repetition

**Origin:** Hermann Ebbinghaus (Forgetting Curve, 1885)

**The Insight:** Memory decays over time in a predictable pattern. Reviewing material just before it's forgotten optimally reinforces long-term retention.

**The Ebbinghaus Forgetting Curve:**
```
100% |●
     |  ●
     |    ●
 50% |      ●
     |        ●
     |          ●●●
     |               ●●●●●●●
     └──────────────────────────→ Time
```

**The Spaced Review Schedule:**
- Review 1: 24 hours after initial learning
- Review 2: 3 days later
- Review 3: 1 week later
- Review 4: 2 weeks later
- Review 5: 1 month later
- Subsequent: Each interval doubles

**Tools:** Anki (flashcard app), RemNote, Obsidian with spaced repetition plugin

**When to use:** Technical learning, language acquisition, certifications, leadership concepts

---

### 5.3 Deep Work (Cal Newport)

**Origin:** Cal Newport (*Deep Work*, 2016)

**Definition:** Cognitively demanding professional activities performed in a state of distraction-free concentration that push your cognitive capabilities to their limit.

**The Deep Work Equation:**
```
High-Quality Work = Time Spent × Intensity of Focus
```

**Deep Work Philosophies:**

| Philosophy | Description | Best For |
|---|---|---|
| **Monastic** | Eliminate all shallow obligations | Full-time researchers, writers |
| **Bimodal** | Alternating deep periods (days to weeks) with connected periods | Executives with periodic deep work needs |
| **Rhythmic** | Fixed daily deep work blocks (2–4 hours each morning) | Most knowledge workers |
| **Journalistic** | Seize deep work windows whenever they appear | Experienced practitioners only |

**Creating Deep Work Conditions:**
- Define a clear ritual: where, when, how long, with what rules
- Execute in blocks (minimum 90 minutes — one full ultradian cycle)
- Remove all notifications during deep work
- Track deep work hours weekly (target: 4 hours/day for knowledge workers)

**When to use:** Complex problem solving, writing, code development, strategy, learning

---

### 5.4 After-Action Review (AAR)

**Origin:** US Army

**The 4 Questions:**
1. What was supposed to happen? (The plan and intent)
2. What actually happened? (The objective reality)
3. What accounts for the difference? (The analysis)
4. What do we sustain and improve? (The lessons)

**AAR Principles:**
- No rank in the room — the AAR is egalitarian
- Focus on systems, not individuals
- Both positive and negative learnings captured
- Actions have owners and due dates

**When to use:** Post-project, post-incident, post-sprint, post-presentation, any significant event

---

## SECTION 6: STRATEGY AND ANALYSIS FRAMEWORKS

### 6.1 Porter's Five Forces

**Origin:** Michael Porter (Harvard, 1979)

**What it is:** A framework for assessing the competitive intensity and attractiveness of an industry.

**The Five Forces:**
1. **Threat of new entrants** — How easy is it for new competitors to enter?
2. **Threat of substitutes** — Can customers switch to a different solution?
3. **Bargaining power of buyers** — How much leverage do customers have?
4. **Bargaining power of suppliers** — How much leverage do suppliers have?
5. **Competitive rivalry** — How intense is competition among existing players?

**Implication:** High forces = low industry attractiveness (commoditisation). Build moats against each force.

**When to use:** Business strategy, market entry analysis, investment assessment

---

### 6.2 SWOT Analysis

**What it is:** A structured framework for assessing an organisation, project, or decision along four dimensions.

| Internal | | External | |
|---|---|---|---|
| **Strengths** | What we do well | **Opportunities** | External conditions we can exploit |
| **Weaknesses** | What we do poorly | **Threats** | External conditions that could harm us |

**SWOT → TOWS (Strategies):**
- S + O: Use strengths to capture opportunities
- W + O: Address weaknesses to unlock opportunities
- S + T: Use strengths to mitigate threats
- W + T: Minimise weaknesses to avoid threat impact

**When to use:** Strategic planning, competitive analysis, project planning

---

### 6.3 The Jobs-to-Be-Done Framework

**Origin:** Clayton Christensen (Harvard)

**The Insight:** Customers don't buy products — they "hire" them to do a job. Understanding the job produces better products and strategies than understanding demographics.

**Types of Jobs:**
- **Functional:** The practical task ("Get me from A to B faster")
- **Emotional:** How they want to feel ("Feel safe and in control")
- **Social:** How they want to be seen ("Look successful")

**JTBD Interview Questions:**
- "Walk me through the last time you used [product/service]"
- "What were you trying to accomplish?"
- "What else did you try before choosing this?"
- "What would you do if this didn't exist?"

**When to use:** Product development, market research, positioning, messaging

---

### 6.4 The Lean Startup Methodology

**Origin:** Eric Ries (*The Lean Startup*, 2011)

**Core Cycle:**
```
BUILD → MEASURE → LEARN
  ↑                 ↓
  └─────────────────┘
```

**Key Concepts:**

| Concept | Definition |
|---|---|
| **MVP (Minimum Viable Product)** | Smallest product that enables validated learning |
| **Validated Learning** | Running an experiment to test a business hypothesis |
| **Pivot** | Structured course correction based on learning |
| **Persevere** | Continue the current strategy when learning validates it |
| **Innovation Accounting** | Measuring progress against learning milestones, not vanity metrics |

**The 3 Engines of Growth:**
- Sticky: Retention (return customers)
- Viral: Referral (customers bring customers)
- Paid: CAC < LTV (paid acquisition pays off)

**When to use:** New product development, startup strategy, innovation programmes

---

### 6.5 Blue Ocean Strategy

**Origin:** W. Chan Kim and Renée Mauborgne (2005)

**The Insight:** Competing in saturated markets (red oceans) is a zero-sum fight. Creating new market space (blue oceans) makes competition irrelevant.

**The Four Actions Framework:**

| Action | Question |
|---|---|
| **Eliminate** | Which factors the industry takes for granted should be eliminated? |
| **Reduce** | Which factors should be reduced well below the industry standard? |
| **Raise** | Which factors should be raised well above the industry standard? |
| **Create** | Which factors should be created that the industry has never offered? |

**When to use:** Strategic planning, innovation, competitive positioning

---

## SECTION 7: AGILE AND DELIVERY FRAMEWORKS

### 7.1 Scrum

**The Core Ceremonies:**

| Ceremony | Frequency | Duration | Purpose |
|---|---|---|---|
| Sprint Planning | Start of sprint | 2–4 hours | Commit to sprint backlog |
| Daily Scrum (Standup) | Daily | 15 min | Synchronise; surface blockers |
| Sprint Review | End of sprint | 1–2 hours | Demo to stakeholders; get feedback |
| Sprint Retrospective | End of sprint | 1–1.5 hours | Inspect and adapt the process |
| Backlog Refinement | Mid-sprint | 1 hour | Groom and estimate future stories |

**The Scrum Roles:**
- **Product Owner:** Owns the backlog; represents business value
- **Scrum Master:** Facilitates ceremonies; removes impediments; protects the team
- **Development Team:** Self-organising; cross-functional; owns delivery

**Definition of Done (DoD):**
The shared understanding of what "complete" means for any story. Must include: coded, unit tested, code reviewed, integration tested, documentation updated, accepted by Product Owner.

---

### 7.2 Kanban

**The Core Principles:**
1. Visualise the workflow
2. Limit work in progress (WIP)
3. Manage flow
4. Make process policies explicit
5. Implement feedback loops
6. Improve collaboratively

**Kanban Board Example:**
```
│ BACKLOG │ IN PROGRESS (max 3) │ REVIEW (max 2) │ DONE │
│─────────│─────────────────────│────────────────│──────│
│ Item A  │      Item D         │    Item F       │ G    │
│ Item B  │      Item E         │                 │ H    │
│ Item C  │                     │                 │ I    │
```

**The Key Metric — Cycle Time:** How long it takes for a work item to move from "In Progress" to "Done." Reducing cycle time is the goal of Kanban improvement.

**When to use:** Operations, support, continuous improvement, non-sprint work

---

### 7.3 SAFe — Scaled Agile Framework

**What it is:** A framework for applying Agile and Lean principles at enterprise scale, across multiple teams.

**Key Concepts:**

| Concept | Definition |
|---|---|
| **PI Planning** | Program Increment Planning — 2-day event where all teams plan together for next 10 weeks |
| **Agile Release Train (ART)** | A long-lived team of Agile teams (50–125 people) that delivers value together |
| **Product Increment (PI)** | A 10-week delivery cycle across all teams in the ART |
| **MVP** | Minimum viable product for learning |
| **Lean Portfolio Management** | Aligning portfolio investments to strategy using Lean and Agile principles |

**When to use:** Large organisations (200+ people) with multiple interdependent teams; avoid for small teams (too heavyweight)

---

### 7.4 The Step-Up Leadership Framework

**What it is:** A framework for understanding and developing leadership capability across career levels.

**The 5 Levels:**

| Level | Identity | Core Discipline | Common Failure Mode |
|---|---|---|---|
| **L1: Individual Contributor** | "I deliver results" | Technical excellence; reliable output | Over-delivering alone; not developing influence |
| **L2: Team Lead / Senior IC** | "I help others deliver" | Coaching; prioritising; unblocking | Doing rather than enabling; poor feedback culture |
| **L3: Manager of Managers** | "I build the system" | Org design; culture; cross-functional leadership | Micromanaging; not developing reports into leaders |
| **L4: Senior Leader / Director** | "I shape the strategy" | Vision; prioritisation across teams; stakeholder leadership | Over-indexing on execution vs. direction |
| **L5: Executive / Org Builder** | "I create the conditions" | Culture architecture; talent; external positioning | Losing touch with operational reality |

**Step-Up Leadership Principles:**
- You cannot lead at the next level with the skills that made you successful at this level
- The transition points (IC → Manager, Manager → Manager of Managers) are identity shifts, not promotions
- The higher you go, the longer the feedback loops — invest in measurement systems
- Your job at every level above IC is to multiply others, not to do more yourself

**The Step-Up Questions (for each level transition):**
1. What do I need to let go of that made me successful at my current level?
2. What new skills do I need to develop?
3. Who can model what success looks like at the next level?
4. What does "making the work visible" look like at the next level?

---

## SECTION 8: BEHAVIOURAL AND PSYCHOLOGICAL FRAMEWORKS

### 8.1 Psychological Safety (Amy Edmondson / Google Project Aristotle)

**Definition:** The belief that one will not be punished or humiliated for speaking up with ideas, questions, concerns, or mistakes.

**Google's Finding (Project Aristotle, 2016):** The single biggest predictor of team performance was psychological safety — more important than talent, tools, or structure.

**The 4 Stages of Psychological Safety (Timothy Clark):**

| Stage | Description | Test Question |
|---|---|---|
| **Inclusion Safety** | I am safe to be myself here | Do I feel accepted as a member of this team? |
| **Learner Safety** | I can ask questions and make mistakes | Can I say "I don't know" without consequences? |
| **Contributor Safety** | I can contribute fully | Can I offer ideas without being dismissed? |
| **Challenger Safety** | I can challenge the status quo | Can I disagree with senior people without fear? |

**Building Psychological Safety:**
- Model vulnerability as a leader (say "I was wrong"; "I don't know")
- Respond to mistakes with curiosity, not blame
- Explicitly invite dissent: "What are we missing?" "Who disagrees?"
- Never punish the messenger of bad news
- Celebrate "intelligent failures" — well-reasoned bets that didn't work out

---

### 8.2 The GROW Coaching Model

**Origin:** Graham Alexander, John Whitmore

| Stage | Purpose | Sample Questions |
|---|---|---|
| **G — Goal** | Clarify what the person wants | "What do you want to achieve?" "What would success look like?" |
| **R — Reality** | Understand the current situation | "Where are you now?" "What have you tried?" "What's working?" |
| **O — Options** | Generate possibilities | "What could you do?" "What else?" "If you couldn't fail, what would you try?" |
| **W — Way Forward** | Commit to action | "What will you do?" "By when?" "What might get in the way?" |

**When to use:** 1:1s, performance conversations, coaching sessions, career development

---

### 8.3 Situational Leadership (Hersey and Blanchard)

**The Insight:** Effective leaders adapt their style to the development level of the individual on the specific task.

**Development Levels:**
- **D1:** Low competence, high commitment (enthusiastic beginner)
- **D2:** Some competence, low commitment (disillusioned learner)
- **D3:** High competence, variable commitment (capable but cautious)
- **D4:** High competence, high commitment (self-reliant achiever)

**Leadership Styles:**
- **S1 — Directing (D1):** High task, low relationship — tell and show how
- **S2 — Coaching (D2):** High task, high relationship — explain and persuade
- **S3 — Supporting (D3):** Low task, high relationship — encourage and collaborate
- **S4 — Delegating (D4):** Low task, low relationship — empower and trust

**The Error:** Using the same style with everyone, or defaulting to delegation because it's comfortable, not because the person is ready.

---

### 8.4 The Lencioni Trust Pyramid

**Origin:** Patrick Lencioni (*The Five Dysfunctions of a Team*)

```
        [Results]         ← Teams without trust can't focus on collective results
           ↑
     [Accountability]     ← Without conflict resolution, accountability suffers
           ↑
    [Commitment]          ← Without genuine debate, people don't commit
           ↑
  [Productive Conflict]   ← Without trust, no one has honest debate
           ↑
      [Trust]             ← Foundation: vulnerability-based trust
```

**Trust (in Lencioni's model):** Vulnerability-based trust — team members are comfortable being open about their weaknesses, failures, and fears.

**Building Trust as a Leader:**
- Go first — be the first to admit mistakes or say "I don't know"
- Create structured sharing opportunities (personal histories, working style exercises)
- Address trust violations directly and immediately

---

## SECTION 9: INNOVATION FRAMEWORKS

### 9.1 The Three Horizons of Growth (McKinsey)

| Horizon | Focus | Timeframe | Leadership Mindset |
|---|---|---|---|
| **H1 — Core** | Optimise the existing business | Now (0–12 months) | Operational excellence |
| **H2 — Adjacent** | Expand into related opportunities | Near (1–3 years) | Entrepreneurial |
| **H3 — Visionary** | Create new growth platforms | Future (3–10 years) | Experimental |

**The Error:** Defaulting to H1 thinking even when the business needs H2 or H3. H1 optimisation cannot solve H3 disruption threats.

---

### 9.2 The OODA Loop

**Origin:** US Air Force Colonel John Boyd

```
OBSERVE → ORIENT → DECIDE → ACT
    ↑                           │
    └───────────────────────────┘
              (Feedback loop)
```

| Stage | What happens |
|---|---|
| **Observe** | Gather raw information from the environment |
| **Orient** | Filter and interpret using mental models, culture, experience |
| **Decide** | Choose a course of action from the options |
| **Act** | Execute the decision |

**The Key Insight:** The **Orient** stage is the most important — it determines what you see and what options you consider. All your biases, mental models, and experience live here.

**Competitive Advantage:** Get inside your competitor's OODA loop (operate faster than they can process and respond).

**When to use:** Crisis response, competitive strategy, rapid decision-making, agile operations

---

## SECTION 10: PERSONAL OPERATING FRAMEWORKS

### 10.1 The Time Audit (Where Your Time Actually Goes)

**The Time Audit Protocol:**
1. For 1 full week, log every activity in 30-minute blocks
2. Categorise each: Deep Work / Shallow Work / Communication / Administration / Meetings
3. Calculate % of time in each category
4. Benchmark against your role's value delivery model
5. Identify 3 time thieves to eliminate; protect 2 deep work blocks daily

**Target Allocation (Knowledge Workers):**

| Activity | Current Avg | Target |
|---|---|---|
| Deep work | 15–20% | 40–60% |
| Strategic meetings | 10% | 15% |
| 1:1s and people | 10% | 20% |
| Admin and shallow | 40–50% | <20% |
| Learning | <5% | 10% |

---

### 10.2 The Personal Productivity Stack

**Morning:**
- 30 min: Review OKRs and daily top-3 priorities (before email)
- Deep work block 1: 90–120 minutes
- Break: Physical movement, natural light

**Midday:**
- Communication and meetings: synchronous collaboration, decisions
- Deep work block 2: 60–90 minutes (when possible)

**End of Day:**
- 15 min: Close loops, update task system, set tomorrow's top 3
- Write one lesson learned from the day

**Weekly:**
- Sunday or Monday: Weekly review (review last week, plan next week)
- Identify top priorities, not tasks
- Review long-term goals: am I still on track?

---

### 10.3 The Energy Management Framework (Jim Loehr and Tony Schwartz)

**The Four Energy Dimensions:**

| Dimension | Source | Depletion Signs | Recovery |
|---|---|---|---|
| **Physical** | Sleep, nutrition, exercise | Fatigue, irritability | Sleep, exercise, rest |
| **Emotional** | Positive emotions, relationships | Negativity, disengagement | Connection, gratitude, nature |
| **Mental** | Focus, challenge | Distraction, shallow thinking | Deep work, mindfulness, novelty |
| **Spiritual** | Purpose, values | Meaninglessness, cynicism | Purpose reflection, contribution |

**The Performance Principle:** Sustainable high performance requires managing recovery as actively as managing output.

**The Ultradian Rhythm:** The brain works in 90-minute cycles. After 90 minutes of focused work, performance degrades until a 15–20 minute recovery break is taken. Structure your deep work in 90-minute blocks.

---

*"A framework is not a cage — it is a scaffold. Use it to build faster and more reliably. Then, when the building stands, the scaffold comes down, and what remains is the work that only you could do, shaped by your judgment, your experience, and your unique perspective. No framework gives you that. It only gives you the structure within which to develop it."*

---

## QUICK REFERENCE INDEX

| Framework | Category | Page Section |
|---|---|---|
| OKRs | Goal-Setting | Section 1.1 |
| SMART Goals | Goal-Setting | Section 1.2 |
| 12-Week Year | Goal-Setting | Section 1.3 |
| Eisenhower Matrix | Prioritisation | Section 2.1 |
| MoSCoW | Prioritisation | Section 2.2 |
| 80/20 Principle | Prioritisation | Section 2.3 |
| ICE Scoring | Prioritisation | Section 2.4 |
| 5 Whys | Problem-Solving | Section 3.1 |
| Fishbone Diagram | Problem-Solving | Section 3.2 |
| PDCA | Problem-Solving | Section 3.3 |
| Design Thinking | Problem-Solving | Section 3.4 |
| Cynefin Framework | Problem-Solving | Section 3.5 |
| Pre-Mortem | Problem-Solving | Section 3.6 |
| Pyramid Principle | Communication | Section 4.1 |
| SCQA | Communication | Section 4.2 |
| Munger Mental Models | Thinking | Section 4.3 |
| Feynman Technique | Learning | Section 4.4 |
| DiSSS | Learning | Section 5.1 |
| Spaced Repetition | Learning | Section 5.2 |
| Deep Work | Learning | Section 5.3 |
| After-Action Review | Learning | Section 5.4 |
| Porter's Five Forces | Strategy | Section 6.1 |
| SWOT / TOWS | Strategy | Section 6.2 |
| Jobs-to-Be-Done | Strategy | Section 6.3 |
| Lean Startup | Strategy | Section 6.4 |
| Blue Ocean Strategy | Strategy | Section 6.5 |
| Scrum | Delivery | Section 7.1 |
| Kanban | Delivery | Section 7.2 |
| SAFe | Delivery | Section 7.3 |
| Step-Up Leadership | Leadership | Section 7.4 |
| Psychological Safety | Behaviour | Section 8.1 |
| GROW Coaching | Behaviour | Section 8.2 |
| Situational Leadership | Behaviour | Section 8.3 |
| Lencioni Trust Pyramid | Behaviour | Section 8.4 |
| Three Horizons | Innovation | Section 9.1 |
| OODA Loop | Decision-Making | Section 9.2 |
| Time Audit | Personal | Section 10.1 |
| Personal Productivity Stack | Personal | Section 10.2 |
| Energy Management | Personal | Section 10.3 |
