"""Workout models package - compositional architecture for analytics.

This package provides a modular organization of workout analytics models:

**Main exports (for backward compatibility):**
- WorkoutMetricsModel: Main API surface
- CanonicalAnalyticsEngine: Computation engine  
- All legacy and substrate models

**Submodules:**
- core: WorkoutMetricsModel and CanonicalAnalyticsEngine (main API)
- constants: Shared constants and utilities
- substrate: CanonicalRecord, CanonicalLap
- legacy: Workout, WorkoutSession, DeviceInfo, RecordSample
- agent: AgentPreferences, AgentPreference, AgentObservation
- metrics: All metric submodels (SessionMetricsModel, etc.)
"""

# Main API (WorkoutMetricsModel and CanonicalAnalyticsEngine)
from .core import CanonicalAnalyticsEngine, WorkoutMetricsModel

# Core substrate models
from .substrate import CanonicalLap, CanonicalRecord

# Legacy models (backward compatibility)
from .legacy import DeviceInfo, RecordSample, Workout, WorkoutSession

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
    # Substrate
    "CanonicalRecord",
    "CanonicalLap",
    # Legacy
    "Workout",
    "WorkoutSession",
    "DeviceInfo",
    "RecordSample",
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
