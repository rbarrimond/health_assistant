"""Agent memory handler for managing user preferences and observations."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Any, Optional

from FitParser.models import AgentPreferences, AgentObservation

logger = logging.getLogger(__name__)

# Error messages
ERR_MISSING_ATHLETE_ID = "Missing required parameter: athlete_id"


class AgentMemoryHandler:
    """Handles agent memory operations (preferences and observations)."""

    def __init__(self, table_storage):
        """Initialize handler with table storage dependency.

        Args:
            table_storage: WorkoutTableStorage instance
        """
        self.table_storage = table_storage

    def get_context(self, athlete_id: str) -> Tuple[Dict[str, Any], int]:
        """Get complete agent context for an athlete.

        Returns preferences and active observations to be used as context
        by the GPT agent at conversation start.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": "Missing required parameter: athlete_id"}, 400

        try:
            # Fetch preferences
            prefs = self._get_preferences_from_storage(athlete_id)

            # Fetch active observations
            observations = self._get_active_observations_from_storage(
                athlete_id
            )

            # Build instruction addendum for GPT
            instruction_parts = []

            if prefs:
                if prefs.get("current_goal"):
                    instruction_parts.append(
                        f"User's current goal: {prefs['current_goal']}")
                if prefs.get("training_phase"):
                    instruction_parts.append(
                        f"Training phase: {prefs['training_phase']}")

            if observations:
                obs_summary = ", ".join([obs["summary"]
                                        for obs in observations[:3]])
                instruction_parts.append(f"Active observations: {obs_summary}")

            return {
                "athlete_id": athlete_id,
                "preferences": prefs or {},
                "active_observations": observations,
                "instruction_addendum": (
                    " | ".join(instruction_parts)
                    if instruction_parts
                    else None
                ),
                "retrieved_at": datetime.now(timezone.utc).isoformat()
            }, 200

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error getting agent context: %s", exc, exc_info=True)
            return {"error": "Failed to retrieve agent context"}, 500

    def get_preferences(self, athlete_id: str) -> Tuple[Dict[str, Any], int]:
        """Get preferences for an athlete.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": ERR_MISSING_ATHLETE_ID}, 400

        try:
            prefs = self._get_preferences_from_storage(athlete_id)
            if not prefs:
                return {"athlete_id": athlete_id, "preferences": {}}, 200
            return {"athlete_id": athlete_id, "preferences": prefs}, 200

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error getting preferences: %s", exc, exc_info=True)
            return {"error": "Failed to retrieve preferences"}, 500

    def update_preferences(
        self,
        athlete_id: str,
        preferences: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], int]:
        """Update preferences for an athlete.

        Args:
            athlete_id: Athlete identifier
            preferences: Dictionary of preference fields to update

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": ERR_MISSING_ATHLETE_ID}, 400

        try:
            # Validate with pydantic model
            pref_data = {"athlete_id": athlete_id, **preferences}
            agent_prefs = AgentPreferences(**pref_data)

            # Store to table
            self._store_preferences(agent_prefs)

            return {
                "athlete_id": athlete_id,
                "preferences": agent_prefs.model_dump(exclude_none=True),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }, 200

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error updating preferences: %s", exc, exc_info=True)
            return {"error": f"Failed to update preferences: {str(exc)}"}, 500

    def add_observation(
        self,
        athlete_id: str,
        category: str,
        summary: str,
        details: Optional[str] = None,
        workout_ids: Optional[List[str]] = None,
        priority: str = "normal",
        expires_days: Optional[int] = None
    ) -> Tuple[Dict[str, Any], int]:
        """Add a new observation for an athlete.

        Args:
            athlete_id: Athlete identifier
            category: Observation category (pattern, flag, insight)
            summary: Brief summary
            details: Optional detailed context
            workout_ids: Optional list of related workout IDs
            priority: Priority level (low, normal, high)
            expires_days: Optional days until observation expires

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id or not category or not summary:
            return {"error": "Missing required parameters"}, 400

        try:
            observation_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc)

            expires_at = None
            if expires_days:
                expires_at = (
                    created_at + timedelta(days=expires_days)
                ).isoformat()

            observation = AgentObservation(
                athlete_id=athlete_id,
                observation_id=observation_id,
                category=category,
                summary=summary,
                details=details,
                referenced_workout_ids=workout_ids or [],
                priority=priority,
                status="active",
                created_at=created_at.isoformat(),
                expires_at=expires_at
            )

            self._store_observation(observation)

            return {
                "observation_id": observation_id,
                "observation": observation.model_dump(exclude_none=True)
            }, 201

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error adding observation: %s", exc, exc_info=True)
            return {"error": f"Failed to add observation: {str(exc)}"}, 500

    def list_observations(
        self,
        athlete_id: str,
        status: str = "active",
        limit: int = 20
    ) -> Tuple[Dict[str, Any], int]:
        """List observations for an athlete.

        Args:
            athlete_id: Athlete identifier
            status: Filter by status (active, resolved, archived, all)
            limit: Maximum number of observations to return

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": ERR_MISSING_ATHLETE_ID}, 400

        try:
            observations = self._get_observations_from_storage(
                athlete_id=athlete_id,
                status=status if status != "all" else None,
                limit=limit
            )

            return {
                "athlete_id": athlete_id,
                "observations": observations,
                "count": len(observations)
            }, 200

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error listing observations: %s", exc, exc_info=True)
            return {"error": "Failed to list observations"}, 500

    def update_observation_status(
        self,
        athlete_id: str,
        observation_id: str,
        status: str
    ) -> Tuple[Dict[str, Any], int]:
        """Update the status of an observation.

        Args:
            athlete_id: Athlete identifier
            observation_id: Observation identifier
            status: New status (active, resolved, archived)

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id or not observation_id or not status:
            return {"error": "Missing required parameters"}, 400

        if status not in ["active", "resolved", "archived"]:
            return {
                "error": (
                    "Invalid status. Must be: active, resolved, or archived"
                )
            }, 400

        try:
            success = self._update_observation_status_in_storage(
                athlete_id, observation_id, status
            )

            if not success:
                return {"error": "Observation not found"}, 404

            return {
                "observation_id": observation_id,
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }, 200

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error updating observation status: %s",
                         exc, exc_info=True)
            return {"error": "Failed to update observation status"}, 500

    # ========================================================================
    # Private storage methods
    # ========================================================================

    def _get_preferences_from_storage(self, athlete_id: str) -> Optional[Dict]:
        """Fetch preferences from AgentPreferences table."""
        client = self.table_storage._get_table_client(  # pylint: disable=protected-access
            "AgentPreferences"
        )

        try:
            entity = client.get_entity(
                partition_key=athlete_id,
                row_key="preferences"
            )
            return self._entity_to_preferences_dict(entity)
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def _store_preferences(self, preferences: AgentPreferences):
        """Store preferences to AgentPreferences table."""
        client = self.table_storage._get_table_client(  # pylint: disable=protected-access
            "AgentPreferences"
        )

        entity = {
            "PartitionKey": preferences.athlete_id,
            "RowKey": "preferences",
            "current_goal": preferences.current_goal,
            "training_phase": preferences.training_phase,
            "preferred_sports": (
                ",".join(preferences.preferred_sports)
                if preferences.preferred_sports
                else ""
            ),
            "ftp_test_frequency_weeks": preferences.ftp_test_frequency_weeks,
            "last_ftp_test_date": preferences.last_ftp_test_date,
            "notes": preferences.notes,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        client.upsert_entity(entity)

    def _get_active_observations_from_storage(
        self,
        athlete_id: str,
        limit: int = 10
    ) -> List[Dict]:
        """Fetch active observations from AgentObservations table."""
        return self._get_observations_from_storage(
            athlete_id=athlete_id,
            status="active",
            limit=limit
        )

    def _get_observations_from_storage(
        self,
        athlete_id: str,
        status: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """Fetch observations from AgentObservations table."""
        client = self.table_storage._get_table_client(  # pylint: disable=protected-access
            "AgentObservations"
        )

        query = f"PartitionKey eq '{athlete_id}'"
        if status:
            query += f" and status eq '{status}'"

        try:
            entities = client.query_entities(query, results_per_page=limit)
            observations = [
                self._entity_to_observation_dict(e) for e in entities]

            # Sort by priority (high first) then created_at
            priority_order = {"high": 0, "normal": 1, "low": 2}
            observations.sort(
                key=lambda x: (
                    priority_order.get(x.get("priority", "normal"), 1),
                    x.get("created_at", "")
                )
            )

            return observations[:limit]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error querying observations: %s", exc)
            return []

    def _store_observation(self, observation: AgentObservation):
        """Store observation to AgentObservations table."""
        client = self.table_storage._get_table_client(  # pylint: disable=protected-access
            "AgentObservations"
        )

        entity = {
            "PartitionKey": observation.athlete_id,
            "RowKey": observation.observation_id,
            "category": observation.category,
            "summary": observation.summary,
            "details": observation.details,
            "referenced_workout_ids": ",".join(observation.referenced_workout_ids),
            "priority": observation.priority,
            "status": observation.status,
            "created_at": observation.created_at,
            "expires_at": observation.expires_at
        }

        client.upsert_entity(entity)

    def _update_observation_status_in_storage(
        self,
        athlete_id: str,
        observation_id: str,
        status: str
    ) -> bool:
        """Update observation status in storage."""
        client = self.table_storage._get_table_client(  # pylint: disable=protected-access
            "AgentObservations"
        )

        try:
            entity = client.get_entity(
                partition_key=athlete_id,
                row_key=observation_id
            )
            entity["status"] = status
            client.update_entity(entity)
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error updating observation status: %s", exc)
            return False

    @staticmethod
    def _entity_to_preferences_dict(entity: Dict) -> Dict:
        """Convert table entity to preferences dictionary."""
        return {
            "athlete_id": entity.get("PartitionKey"),
            "current_goal": entity.get("current_goal"),
            "training_phase": entity.get("training_phase"),
            "preferred_sports": (
                entity.get("preferred_sports", "").split(",")
                if entity.get("preferred_sports")
                else []
            ),
            "ftp_test_frequency_weeks": entity.get("ftp_test_frequency_weeks"),
            "last_ftp_test_date": entity.get("last_ftp_test_date"),
            "notes": entity.get("notes"),
            "updated_at": entity.get("updated_at")
        }

    @staticmethod
    def _entity_to_observation_dict(entity: Dict) -> Dict:
        """Convert table entity to observation dictionary."""
        return {
            "athlete_id": entity.get("PartitionKey"),
            "observation_id": entity.get("RowKey"),
            "category": entity.get("category"),
            "summary": entity.get("summary"),
            "details": entity.get("details"),
            "referenced_workout_ids": (
                entity.get("referenced_workout_ids", "").split(",")
                if entity.get("referenced_workout_ids")
                else []
            ),
            "priority": entity.get("priority", "normal"),
            "status": entity.get("status", "active"),
            "created_at": entity.get("created_at"),
            "expires_at": entity.get("expires_at")
        }
