# Copilot Constitution — Workout Intelligence Agent

This document governs how Copilot must behave when analyzing or modifying code in this repository.

This system prioritizes correctness, reproducibility, semantic clarity, and long-term architectural integrity over speed, novelty, or cleverness.

When in conflict, prefer architectural discipline.

---

## I. Documentation Is Sovereign

- The `docs/` directory is the authoritative source of truth.
- Code must conform to documentation.
- If documentation and code diverge, surface the divergence explicitly.
- Never silently reconcile contradictions.

Documentation > Assumption  
Explicit reference > Inference  

---

## II. Object-Oriented Discipline Is Mandatory

This system adheres to strict Object-Oriented Analysis and Design (OOAD) principles.

Prefer:

- Encapsulated domain models
- Explicit contracts
- Typed boundaries
- Dependency injection
- Stateless services
- Idempotent operations

Reject:

- Procedural sprawl
- Hidden coupling
- Implicit global state
- Cross-layer leakage
- Schema mutation without version bump

Clarity > Cleverness  
Structure > Convenience  
Explicitness > Implicit magic  

---

## III. Invariants and Versioning Are Sacred

- Do not alter ingestion, parsing, storage schema, or persisted semantics without a version bump.
- Any change affecting persisted semantics requires:
  - SemVer bump
  - CHANGELOG entry
  - Schema documentation update
- Follow SemVer rigorously. Breaking changes require a major version increment.

If satisfying a requested change would violate a documented invariant, surface the violation rather than working around it.

Stability > Speed  
Integrity > Expedience  

---

## IV. Scope Discipline with Integrity

- Edits must remain scoped to the explicit request.
- Do not introduce speculative refactors.
- Do not expand scope for stylistic improvements.

However:

If a requested change will:

- Break documented invariants,
- Violate type contracts,
- Introduce cascading compile/runtime failures,
- Or create architectural inconsistency,

Then:

1. Surface the impact explicitly.
2. Explain what additional changes would be required to preserve system integrity.
3. Request confirmation before widening scope.

Integrity > Blind scope adherence  

Silent breakage is unacceptable.  
Silent refactor expansion is unacceptable.  

---

## V. Library Stewardship

- Do not reimplement functionality already provided by project dependencies.
- Review `requirements.txt` and `pyproject.toml` before introducing new utilities.
- Prefer established, tested libraries over custom implementations.
- Prefer existing project abstractions over introducing parallel ones.

Before adding or suggesting new dependencies you MUST do the following:

1. Verify the capability does not already exist.
2. Justify why a new dependency is necessary.
3. Attempt to avoid duplicating behavior in multiple forms such as:
   - utility functions that replicate existing library features
   - wrappers that replicate existing abstractions
   - or new classes that replicate existing domain models
   - especially if the new code would introduce divergence in behavior or semantics.

If a library abstraction conflicts with documented invariants:

- Surface the mismatch explicitly.
- Do not silently work around it.
- Do not bend domain semantics to accommodate a library.

Composition > Reinvention  
Reuse > Novelty  
Domain Integrity > Library Convenience  

---

## VI. Static Analysis and Linting Discipline

- Write code that naturally satisfies linters and type checkers.
- Prefer explicit typing over casting to silence warnings.
- Do not use type coercion, `Any`, blanket ignores, or suppression comments to bypass legitimate structural issues.
- Treat linter or type-check failures in production code as design signals, not annoyances.

Correct modeling > Warning suppression  
Explicit types > Casting hacks  

If satisfying the linter requires architectural compromise:

- Surface the tension explicitly.
- Do not suppress the warning to “make it green.”

However:

- Generated test code and mechanical scaffolding may silence lint or type warnings when necessary.
- Test code is permitted to prioritize functionality over architectural purity.
- Lint suppression in tests must not leak into production modules.

Production integrity > Test strictness  
Signal > Silence  

---

## VII. Exception Semantics

- Preserve exception causality at abstraction boundaries.
- When wrapping or translating exceptions, use explicit chaining:

  raise DomainError("...") from exc

- Do not swallow exceptions.
- Do not replace exceptions without preserving their cause.
- Do not leak low-level infrastructure exceptions into domain or API layers.
- If a new error category is required, propose extending the existing exception hierarchy in `TrainingAnalyticsPlatform/platform/exceptions.py` rather than inventing ad-hoc exception classes.
- New exceptions must represent meaningful semantic categories, not hyper-specific runtime circumstances. Leverage exception attributes for contextual details rather than proliferating classes.
- Avoid exception proliferation. Do not create overly granular classes such as `ValueErrorBecauseTheBigEndianMathExecutedAfterFourPM`.

Hierarchy coherence > Novelty  
Semantic taxonomy > One-off cleverness  

Error transparency > Convenience  

---

## VIII. Human Legibility Requirement

This codebase must remain readable by a senior engineer six months from now without relying on memory.

Prefer:

- Explicit names
- Clear structure
- Logical separation
- Predictable patterns

Avoid:

- Clever compression
- Abstraction for its own sake
- Pattern overuse
- Opaque one-liners

Human comprehension > Intellectual display  

---

## IX. Plan Mode Discipline

In Plan mode:

- Treat questions as requests for analysis and clarification — not as instructions to modify the plan.
- Answer the question directly before proposing structural changes.
- Do not silently rewrite or expand the plan unless explicitly instructed.
- If a question reveals a flaw in the current plan, explain the flaw and propose a revision rather than modifying it unilaterally.
- Reference specific documentation or code sections when reasoning.

Analysis > Speculation  
Clarity > Premature optimization  
Explanation > Silent adjustment  
