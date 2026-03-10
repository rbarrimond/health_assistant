"""Workout models package - compositional architecture for analytics.

This package provides a modular organization of workout analytics models:

**Main exports:**
- WorkoutMetricsModel: Main API surface
- CanonicalAnalyticsEngine: Computation engine
- Substrate models

**Submodules:**
- core: WorkoutMetricsModel and CanonicalAnalyticsEngine (main API)
- constants: Shared constants and utilities
- substrate: CanonicalRecord, CanonicalRecordSet, CanonicalLap
- legacy: removed in v8.0.0
- agent: AgentPreferences, AgentPreference, AgentObservation
- metrics: All metric submodels (SessionMetricsModel, etc.)
"""

# Main API (WorkoutMetricsModel and CanonicalAnalyticsEngine)
from .core import CanonicalAnalyticsEngine, WorkoutDetailResponse, WorkoutMetricsModel

# Core substrate models
from .substrate import CanonicalLap, CanonicalRecord, CanonicalRecordSet

# Agent memory models
from .agent import AgentObservation, AgentPreference, AgentPreferences

# Metric submodels
from .metrics import (
    DistanceMetricsModel,
    DurabilityMetricsModel,
    EnvelopeScoresModel,
    HRZonesModel,
    PowerDurationAnchorsModel,
    PowerZonesModel,
    SampleMetricsModel,
    SessionMetricsModel,
    StructuredArtifactsModel,
    TrainingLoadMetricsModel,
    VariabilityMetricsModel,
)

__all__ = [
    # Main API
    "WorkoutMetricsModel",
    "CanonicalAnalyticsEngine",
    "WorkoutDetailResponse",
    # Substrate
    "CanonicalRecord",
    "CanonicalRecordSet",
    "CanonicalLap",
    # Agent
    "AgentPreferences",
    "AgentPreference",
    "AgentObservation",
    # Metrics
    "SessionMetricsModel",
    "SampleMetricsModel",
    "DistanceMetricsModel",
    "HRZonesModel",
    "PowerZonesModel",
    "TrainingLoadMetricsModel",
    "PowerDurationAnchorsModel",
    "EnvelopeScoresModel",
    "VariabilityMetricsModel",
    "DurabilityMetricsModel",
    "StructuredArtifactsModel",
]
