# Runtime Chaos Injection (local only)

This project supports runtime fault injection without modifying application code.
It uses Python's `sitecustomize` hook and only activates when `CHAOS_TARGET` is set.

## Quick start

1) Ensure the debugger task is used (it already sets `PYTHONPATH` for `sitecustomize`).
2) Add these values to `local.settings.json`:

```json
{
  "IsEncrypted": false,
  "Values": {
    "CHAOS_TARGET": "function_app._ingest_fit_payload",
    "CHAOS_RATE": "0.2",
    "CHAOS_SLEEP_MS": "250",
    "CHAOS_MESSAGE": "Injected failure"
  }
}
```

1) Start the Functions host from the VS Code debugger.

## Environment variables

- `CHAOS_TARGET` (required): Dotted path to a callable to wrap.
  - Default target for idempotency testing: `function_app._ingest_fit_payload`.
- `CHAOS_RATE` (optional): Float in 0..1, probability of raising per call.
- `CHAOS_AFTER` (optional): Int, only raise after N calls have occurred.
- `CHAOS_ONCE` (optional): If true, raise only once.
- `CHAOS_SLEEP_MS` (optional): Int, sleep milliseconds before each call.
- `CHAOS_MESSAGE` (optional): Exception message for the injected failure.

## Common targets

- `function_app._ingest_fit_payload`: Fail early in the ingestion flow.
- `FitParser.fit_parser.FitParser.parse`: Fail during FIT parsing.
- `FitParser.table_storage.WorkoutTableStorage.store_workout`: Fail on Workouts write.

## Notes

- This is local-only and is a no-op unless `CHAOS_TARGET` is set.
- The injector lives in `scripts/chaos/sitecustomize.py`.
