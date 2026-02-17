"""Agent memory models for preferences and observations.

These models support the LLM agent's ability to remember athlete preferences,
training goals, and observations about patterns over time.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from .constants import ATHLETE_ID_DESC, ISO_8601_UTC_DESC, LAST_UPDATE_DESC


class AgentPreferences(BaseModel):
    """Legacy single-record preferences for the agent."""

    athlete_id: str = Field(description=ATHLETE_ID_DESC)
    current_goal: Optional[str] = Field(
        None, description="Current training goal or race target"
    )
    training_phase: Optional[str] = Field(
        None, description="Current training phase (e.g., 'base-building', 'build', 'peak', 'recovery')"
    )
    preferred_sports: List[str] = Field(
        default_factory=list, description="Preferred sports in priority order"
    )
    ftp_test_frequency_weeks: Optional[int] = Field(
        None, description="How often to prompt for FTP testing"
    )
    last_ftp_test_date: Optional[str] = Field(
        None, description="ISO 8601 date of last FTP test"
    )
    notes: Optional[str] = Field(
        None, description="Free-form context notes"
    )
    updated_at: Optional[str] = Field(None, description=LAST_UPDATE_DESC)


class AgentPreference(BaseModel):
    """Preference item for agent memory."""

    athlete_id: str = Field(description=ATHLETE_ID_DESC)
    preference_id: str = Field(description="Unique preference identifier")
    category: str = Field(description="Preference category (goal, constraint, routine, etc.)")
    summary: str = Field(description="Brief preference summary")
    details: Optional[str] = Field(None, description="Detailed preference context")
    priority: str = Field(
        default="normal", description="Priority level: low, normal, high"
    )
    status: str = Field(
        default="active", description="Status: active, resolved, archived"
    )
    created_at: str = Field(description=ISO_8601_UTC_DESC)
    updated_at: Optional[str] = Field(None, description=LAST_UPDATE_DESC)


class AgentObservation(BaseModel):
    """Agent observations and flags for future reference."""

    athlete_id: str = Field(description=ATHLETE_ID_DESC)
    observation_id: str = Field(description="Unique observation identifier")
    category: str = Field(
        description="Observation category (e.g., 'pattern', 'flag', 'insight')"
    )
    summary: str = Field(description="Brief observation summary")
    details: Optional[str] = Field(None, description="Detailed observation context")
    referenced_workout_ids: List[str] = Field(
        default_factory=list, description="Related workout IDs"
    )
    priority: str = Field(
        default="normal", description="Priority level: low, normal, high"
    )
    status: str = Field(
        default="active", description="Status: active, resolved, archived"
    )
    created_at: str = Field(description=ISO_8601_UTC_DESC)
    expires_at: Optional[str] = Field(
        None, description="ISO 8601 UTC timestamp when observation expires"
    )
