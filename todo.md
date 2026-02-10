# TODO

| Area | Task | Details / Constraints | Status | Complete |
| --- | --- | --- | --- | --- |
| Timezone Semantics | Define athlete home timezone | First-class concept; authoritative for weeks, days, rollups | ⬜ | ⬜ |
| Timezone Semantics | Interpret data in local time | Store UTC, interpret in athlete timezone | ⬜ | ⬜ |
| Timezone Semantics | Hide UTC from UI | UTC never surfaced to athlete | ⬜ | ⬜ |
| Semantic Layer | Document timestamp meaning | `start_time_utc` / `end_time_utc` are storage fields | ⬜ | ⬜ |
| Semantic Layer | Document timezone usage | Contextual only; not grouping authority | ⬜ | ⬜ |
| Semantic Layer | Rollup computation rule | Always use athlete home timezone | ⬜ | ⬜ |
| Athlete Context | Set home timezone | `America/New_York` | ⬜ | ⬜ |
| Athlete Context | Time interpretation preference | Athlete thinks in local time | ⬜ | ⬜ |
| Athlete Context | Distance units | Imperial (miles, feet) | ⬜ | ⬜ |
| Athlete Context | Power units | Watts absolute, W/kg relative | ⬜ | ⬜ |
| Athlete Context | Week definition | Week starts Monday, local timezone | ⬜ | ⬜ |
| Workout Interpretation | Virtual vs outdoor heuristic | GPS vs timezone agreement | ⬜ | ⬜ |
| Workout Interpretation | Preserve raw data | No mutation of source workouts | ⬜ | ⬜ |
| Weekly Rollups | Design rollup schema | Deterministic, cacheable | ⬜ | ⬜ |
| Weekly Rollups | Enforce week boundaries | Prevent workouts appearing in two weeks | ⬜ | ⬜ |
| Weekly Rollups | Core metrics | Sessions, intensity min, Z2 min, flags | ⬜ | ⬜ |
| Week Classification | Define week types | Hard / Normal / Recovery | ⬜ | ⬜ |
| Week Classification | Classification signals | Intensity density & distribution | ⬜ | ⬜ |
| UI Contract | Backend ownership | Time, grouping, rollups, classification | ⬜ | ⬜ |
| UI Contract | UI ownership | Language, emphasis, reactions | ⬜ | ⬜ |
| MVP Validation | Fast week summary | "How was last week?" answered instantly | ⬜ | ⬜ |
| MVP Validation | Correct day placement | Late-night sessions behave intuitively | ⬜ | ⬜ |
| MVP Validation | Athlete trust | System feels like it noticed the athlete | ⬜ | ⬜ |
| Explicit Non-Goals | Defer travel timezone shifts | No auto-switching yet | ⬜ | ⬜ |
| Explicit Non-Goals | Avoid prescriptions | No training advice at this stage | ⬜ | ⬜ |
