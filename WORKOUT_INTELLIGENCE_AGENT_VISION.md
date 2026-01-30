# - Workout Intelligence Agent — Vision & Operating Model

This document describes the **intentional design** of the Workout Intelligence Agent:  
what it is, what it is *not*, how it behaves, and why it stays usable in ad hoc, real-world use.

This is **not** an AI toy.  
It is a **deterministic data system with a conversational UI**.

---

## 1. Core Philosophy

### Determinism first, intelligence second

- **Metrics are facts**, not suggestions.
- All calculations (zones, minutes, decoupling, rollups) are:
  - deterministic
  - reproducible
  - versioned
- No LLM ever computes metrics.

The agent reasons **over** data — it never invents it.

---

### ChatGPT is the UI, not the system

- The agent’s “brain” is your **metrics database + API**
- ChatGPT is:
  - the **ad hoc interface**
  - the **reasoning layer**
  - the **planner / explainer**

If ChatGPT disappears tomorrow, the system still works.

---

### Ad hoc is the primary use case

This agent is built for:

- “What should I do tomorrow?”
- “Why am I feeling flat this week?”
- “Show me how my Z2 quality has changed since December”
- “Am I accumulating too much intensity relative to base?”

Not just:

- “This week vs last week”
- “Here’s a dashboard”

Dashboards are optional. **Conversation is mandatory.**

---

## 2. What the Agent Is

### A three-part system

 [ Ingestion ] → [ Metrics DB ] → [ Read API ] → [ ChatGPT UI ]

#### 1) Ingestion (Python, deterministic)

- Watches iCloud Drive `/HealthFit/*.fit` (via WebDAV sync)
- Parses FIT files
- Computes:
  - summaries
  - zones
  - rollups
  - efficiency metrics
- Writes immutable facts to the DB

This layer:

- has no opinions
- has no heuristics
- has no “coaching logic”

It is a calculator.

---

#### 2) Metrics Database (Truth Layer)

- Stores **what happened**
- Never stores “recommendations”
- Never stores “interpretations”

Responsibilities:

- retain historical meaning (FTP-at-the-time, zone definitions)
- support queries across arbitrary windows
- remain stable as tools change

This DB is the **training log you wish Garmin actually gave you**.

---

#### 3) Read API (Semantic Access Layer)

This is the *agent* in the architectural sense.

It exposes **meaningful questions**, not raw tables.

Examples:

- `/planning/context?days=45`
- `/rollups/weekly?weeks=16`
- `/workouts?since=2026-01-01&limit=50`
- `/workouts/{id}`

This layer:

- shapes data for reasoning
- constrains scope
- protects performance
- encodes *how humans think about training*

---

## 3. What the Agent Is NOT

### ❌ Not a rules engine

- No “if Z2 \< X then do Y” logic lives in the system.
- Those judgments happen in ChatGPT, with you in the loop.

### ❌ Not a coach replacement

- It does not tell you what to do *without context*.
- It surfaces **tradeoffs**, **signals**, and **patterns**.

### ❌ Not a dashboard-first product

- Dashboards answer predefined questions.
- You want to ask *new* questions.

The agent exists because dashboards plateau.

---

## 4. Responsibilities by Layer

### Ingestion Layer (Python)

#### Must do (Ingestion)

- parse FIT reliably
- compute zones correctly
- store FTP and HR references
- version its own outputs

#### Must not (Ingestion)

- infer training intent
- assess “good vs bad”
- smooth or “correct” data

---

### Metrics DB

#### Must do (Metrics DB)

- preserve historical truth
- support arbitrary time windows
- remain queryable at scale

#### Must not (Metrics DB)

- store transient interpretations
- depend on UI assumptions

---

### Read API

#### Must do (Read API)

- return small, coherent payloads
- answer *semantic* questions
- be stable enough for GPT Actions

#### Must not (Read API)

- expose raw time series by default
- leak ingestion complexity upward

---

### ChatGPT (UI / Reasoning Layer)

#### Must do (ChatGPT)

- synthesize across signals
- explain tradeoffs
- plan forward with uncertainty
- speak in human terms

#### Must not (ChatGPT)

- fabricate metrics
- override known data
- pretend certainty where none exists

---

## 5. The Planning Context Contract (Key Insight)

The single most important endpoint:

 GET /api/planning/context?days=N

It returns:

- recent workouts (summaries only)
- weekly rollups covering the window
- last hard day
- last long day
- cumulative Z2
- cumulative intensity
- notable flags (missing HR, excessive drift, etc.)

This payload answers:
> “Given what I’ve actually done, what does tomorrow look like?”

Everything else is secondary.

---

## 6. Ad Hoc Interaction Model (How You’ll Actually Use It)

You will ask things like:

- “Why did Garmin think I was unproductive this week?”
- “Is my aerobic efficiency improving or am I just accumulating volume?”
- “Do I need intensity tomorrow or more low aerobic?”
- “Am I getting CNS stress without enough base?”

The agent:

1. fetches the *right slice* of data
2. reasons across **patterns**, not single workouts
3. explains *why* a recommendation makes sense
4. leaves room for judgment

---

## 7. Why This Scales (Mentally and Technically)

### Mentally

- You don’t have to remember what to look for
- You don’t have to predefine dashboards
- You can follow curiosity

### Technically

- Data volume grows linearly
- Queries stay bounded
- The API surface stays small
- The UI stays flexible

This system improves as your history grows.

---

## 8. Evolution Path (Without Rewrites)

### Phase 1 (now)

- FIT → metrics → API → ChatGPT
- Single athlete
- Simple planning

### Phase 2

- Precomputed rollups
- Fatigue heuristics (still deterministic)
- Comparison windows (“best 6-week block”)

### Phase 3 (optional)

- Multi-athlete (same schema)
- Longitudinal modeling
- Exportable insights (email, notes)

The **data contract does not change**.

---

## 9. The Design Principle That Matters Most

> **You don’t want the system to tell you what to do.  
> You want it to tell you what is true, and why that matters.**

That is what makes this agent usable, durable, and worth building.

---

## 10. Summary

- Deterministic ingestion
- Stable metrics DB
- Semantic read API
- ChatGPT as the ad hoc UI
- No magic, no hallucinations, no dashboards-as-a-crutch

This is **training intelligence**, not training automation.

And it will age well.
