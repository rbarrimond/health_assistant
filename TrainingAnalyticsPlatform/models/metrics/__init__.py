"""Workout metrics submodels organized by semantic categories."""

from .artifacts import StructuredArtifactsModel
from .distance import DistanceMetricsModel
from .performance import DurabilityMetricsModel, VariabilityMetricsModel
from .samples import SampleMetricsModel
from .session import SessionMetricsModel
from .training import (
    EnvelopeScoresModel,
    PowerDurationAnchorsModel,
    TrainingLoadMetricsModel,
)
from .zones import HRZonesModel, PowerZonesModel

__all__ = [
    # Session
    "SessionMetricsModel",
    # Samples
    "SampleMetricsModel",
    # Distance
    "DistanceMetricsModel",
    # Zones
    "HRZonesModel",
    "PowerZonesModel",
    # Training Load
    "TrainingLoadMetricsModel",
    "PowerDurationAnchorsModel",
    "EnvelopeScoresModel",
    # Performance
    "VariabilityMetricsModel",
    "DurabilityMetricsModel",
    # Artifacts
    "StructuredArtifactsModel",
]
