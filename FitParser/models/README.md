# FitParser Models

Pydantic v2 data models for workout parsing, storage, and analytics.

## Package Structure

``` plaintext
models/
├── core.py          # WorkoutMetricsModel, CanonicalAnalyticsEngine
├── substrate.py     # CanonicalRecord, CanonicalLap (1 Hz telemetry)
├── legacy.py        # Workout, WorkoutSession, DeviceInfo, RecordSample
├── agent.py         # AgentPreferences, AgentObservation
├── constants.py     # Shared utilities, decorators (@numeric_series)
└── metrics/         # Compositional metric submodels
    ├── session.py      # SessionMetricsModel
    ├── samples.py      # SampleMetricsModel
    ├── distance.py     # DistanceMetricsModel
    ├── zones.py        # HRZonesModel, PowerZonesModel
    ├── training.py     # TrainingLoadMetricsModel, PowerDurationAnchorsModel, EnvelopeScoresModel
    ├── performance.py  # VariabilityMetricsModel, DurabilityMetricsModel
    └── artifacts.py    # StructuredArtifactsModel
```

## Design Philosophy

### Composition Over Flat Structures

`WorkoutMetricsModel` uses **typed compositional submodels** instead of 100+ flat fields:

```python
from FitParser.models import WorkoutMetricsModel

# Fields are organized into semantic groups
metrics = WorkoutMetricsModel.from_canonical(df, metadata)

# Access via typed submodels
print(metrics.session.elapsed_time_sec)
print(metrics.hr_zones.zone2_time_sec)
print(metrics.training.tss)
```

**Benefits:**

- Type safety with nested models
- Clear semantic grouping
- IDE autocomplete for submodel fields
- Easier testing of field groups

### Separation of Concerns

**Storage Models** (`legacy.py`):

- `Workout`, `WorkoutSession` - Azure Table entity shapes
- Direct 1:1 with stored data
- Minimal validation, optimized for serialization

**Analytics Models** (`core.py`):

- `WorkoutMetricsModel` - In-memory computed metrics cache
- `CanonicalAnalyticsEngine` - Computation engine for deriving metrics
- Heavy validation, vectorized pandas operations

**Substrate Models** (`substrate.py`):

- `CanonicalRecord` - 1 Hz resampled telemetry row
- `CanonicalLap` - Lap-level aggregated metrics
- Schema contract for analytics computations

### In-Memory Caching Pattern

The `WorkoutMetricsModel.from_canonical()` classmethod enables **compute-once, access-many**:

```python
# Before: Recompute on every property access
engine = CanonicalAnalyticsEngine(canonical_df, metadata)
tss = engine.tss  # Computes
np_watts = engine.np_watts  # Computes again

# After: Compute once, cache in typed structure
metrics = WorkoutMetricsModel.from_canonical(canonical_df, metadata)
tss = metrics.training.tss  # Cached
np_watts = metrics.training.np_watts  # Cached
```

Engine is still available for on-demand computation:

```python
engine = CanonicalAnalyticsEngine(canonical_df, metadata)
custom_metric = engine._compute_custom_analysis()  # Not cached
```

## Usage Examples

### Import All Models (Backward Compatible)

```python
from FitParser.models import (
    WorkoutMetricsModel,
    CanonicalAnalyticsEngine,
    CanonicalRecord,
    CanonicalLap,
    Workout,
    WorkoutSession,
    SessionMetricsModel,
    HRZonesModel,
    # ... all models re-exported from package __init__.py
)
```

### Construct Metrics from Canonical DataFrame

```python
import pandas as pd
from FitParser.models import WorkoutMetricsModel

# 1 Hz canonical telemetry
canonical_df = pd.DataFrame({...})  # CanonicalRecord schema
metadata = {...}  # Activity metadata

# Compute all metrics once
metrics = WorkoutMetricsModel.from_canonical(canonical_df, metadata)

# Access typed submodels
print(f"Duration: {metrics.session.elapsed_time_sec}s")
print(f"TSS: {metrics.training.tss}")
print(f"Avg Power: {metrics.samples.avg_power_watts}W")
print(f"Z2 Time: {metrics.hr_zones.zone2_time_sec}s")
```

### Serialize to Dict (for Table Storage)

```python
metrics_dict = metrics.model_dump(mode='json')
# Returns flat dict with all nested fields flattened for storage
```

### Validate Canonical Schema

```python
from FitParser.models import CanonicalRecord

# Validate DataFrame schema matches CanonicalRecord
records = [CanonicalRecord(**row) for _, row in canonical_df.iterrows()]
```

## Validation & Type Safety

All models use Pydantic v2 validation:

```python
from FitParser.models import SessionMetricsModel

# Automatic type coercion and validation
session = SessionMetricsModel(
    elapsed_time_sec=3600,
    moving_time_sec="3500",  # Coerced to int
    # ... Pydantic validates required fields, types, constraints
)
```

## Computed Fields

Analytics models use `@computed_field` for derived values:

```python
from pydantic import computed_field

class CanonicalAnalyticsEngine(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    canonical_df: pd.DataFrame
    
    @computed_field
    @property
    def tss(self) -> Optional[float]:
        """Training Stress Score from NP and IF."""
        # Computed on-demand from canonical_df
        return self._compute_tss()
```

## Backward Compatibility

Package `__init__.py` re-exports all models for seamless migration:

```python
# Old import (still works)
from FitParser.models import WorkoutMetricsModel

# New import (explicit submodule)
from FitParser.models.core import WorkoutMetricsModel

# Both work identically
```

All existing code using `from FitParser.models import X` continues to work without changes.

## Schema Versions

Models align with versioned schemas:

- **Ingestion Schema**: 4.1.1 (see `docs/devops/INGESTION_SCHEMA.md`)
- **Workout Schema**: 10.0.0 (see `docs/gpt/WORKOUT_SCHEMA.md`)
- **Ingest Version**: v4.1.1 (metadata field)

Bump versions when changing stored data structures or canonical computation contracts.

## Testing

All models have comprehensive test coverage:

```bash
pytest tests/test_fit_parser.py          # Legacy model tests
pytest tests/test_canonical_validation.py # Analytics engine tests
pytest tests/test_handlers_example.py     # Integration tests
```

381 tests validate model construction, serialization, and analytics computations.
