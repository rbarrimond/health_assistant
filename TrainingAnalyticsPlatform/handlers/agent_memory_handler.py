"""Agent memory handler for managing user preferences and observations."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Any, Optional

from TrainingAnalyticsPlatform.models import AgentPreference, AgentObservation, AgentPreferences

logger = logging.getLogger(__name__)

# Error messages
ERR_MISSING_ATHLETE_ID = "Missing required parameter: athlete_id"
ERR_MISSING_REQUIRED_PARAMS = "Missing required parameters"


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
            # Fetch active preferences
            preferences = self._get_active_preferences_from_storage(athlete_id)

            # Fetch active observations
            observations = self._get_active_observations_from_storage(
                athlete_id
            )

            # Build instruction addendum for GPT
            instruction_parts = []

            if preferences:
                goal = self._get_preference_summary(
                    preferences, {"goal", "current_goal"}
                )
                if goal:
                    instruction_parts.append(
                        f"User's current goal: {goal}")

                phase = self._get_preference_summary(
                    preferences, {"training_phase", "phase"}
                )
                if phase:
                    instruction_parts.append(
                        f"Training phase: {phase}")

                remaining = [
                    pref["summary"]
                    for pref in preferences
                    if pref.get("summary")
                    and pref.get("category") not in {
                        "goal",
                        "current_goal",
                        "training_phase",
                        "phase",
                    }
                ]
                if remaining:
                    instruction_parts.append(
                        f"Preferences: {', '.join(remaining[:3])}")

            if observations:
                obs_summary = ", ".join(
                    [obs["summary"] for obs in observations[:3]]
                )
                instruction_parts.append(f"Active observations: {obs_summary}")

            return {
                "athlete_id": athlete_id,
                "preferences": preferences,
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

    def get_preferences(
        self,
        athlete_id: str,
        status: str = "active",
        limit: int = 20
    ) -> Tuple[Dict[str, Any], int]:
        """List preferences for an athlete.

        Args:
            athlete_id: Athlete identifier
            status: Filter by status (active, resolved, archived, all)
            limit: Maximum number of preferences to return

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": ERR_MISSING_ATHLETE_ID}, 400

        try:
            preferences = self._get_preferences_from_storage(
                athlete_id=athlete_id,
                status=status if status != "all" else None,
                limit=limit
            )

            return {
                "athlete_id": athlete_id,
                "preferences": preferences,
                "count": len(preferences)
            }, 200

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error getting preferences: %s", exc, exc_info=True)
            return {"error": "Failed to retrieve preferences"}, 500

    def update_preferences(
        self,
        athlete_id: str,
        preferences: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], int]:
        """Update legacy single-record preferences for an athlete."""
        if not athlete_id:
            return {"error": ERR_MISSING_ATHLETE_ID}, 400
        if not preferences:
            return {"error": ERR_MISSING_REQUIRED_PARAMS}, 400

        try:
            validated = AgentPreferences(athlete_id=athlete_id, **preferences)
            client = self.table_storage._get_table_client(  # pylint: disable=protected-access
                "AgentPreferences"
            )

            entity = {
                "PartitionKey": athlete_id,
                "RowKey": "preferences",
                "current_goal": validated.current_goal,
                "training_phase": validated.training_phase,
                "preferred_sports": ",".join(validated.preferred_sports),
                "ftp_test_frequency_weeks": validated.ftp_test_frequency_weeks,
                "last_ftp_test_date": validated.last_ftp_test_date,
                "notes": validated.notes,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

            client.upsert_entity(entity)

            return {
                "athlete_id": athlete_id,
                "preferences": self._entity_to_legacy_preferences_dict(entity)
            }, 200
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error updating preferences: %s", exc, exc_info=True)
            return {"error": "Failed to update preferences"}, 500

    def add_preference(
        self,
        athlete_id: str,
        category: str,
        summary: str,
        details: Optional[str] = None,
        priority: str = "normal",
        status: str = "active"
    ) -> Tuple[Dict[str, Any], int]:
        """Add a new preference for an athlete."""
        if not athlete_id or not category or not summary:
            return {"error": ERR_MISSING_REQUIRED_PARAMS}, 400

        try:
            preference_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()

            preference = AgentPreference(
                athlete_id=athlete_id,
                preference_id=preference_id,
                category=category,
                summary=summary,
                details=details,
                priority=priority,
                status=status,
                created_at=created_at
            )

            self._store_preference(preference)

            return {
                "preference_id": preference_id,
                "preference": preference.model_dump(exclude_none=True)
            }, 201

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error adding preference: %s", exc, exc_info=True)
            return {"error": f"Failed to add preference: {str(exc)}"}, 500

    def update_preference(
        self,
        athlete_id: str,
        preference_id: str,
        updates: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], int]:
        """Update a preference (status, summary, details, etc.)."""
        if not athlete_id or not preference_id or not updates:
            return {"error": ERR_MISSING_REQUIRED_PARAMS}, 400

        status = updates.get("status")
        if status and status not in ["active", "resolved", "archived"]:
            return {
                "error": (
                    "Invalid status. Must be: active, resolved, or archived"
                )
            }, 400

        allowed_fields = {"category", "summary", "details", "priority", "status"}
        updates = {k: v for k, v in updates.items() if k in allowed_fields}
        if not updates:
            return {"error": "No updatable fields provided"}, 400

        try:
            success, updated = self._update_preference_in_storage(
                athlete_id, preference_id, updates
            )

            if not success:
                return {"error": "Preference not found"}, 404

            return {
                "preference_id": preference_id,
                "preference": updated
            }, 200

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error updating preference: %s", exc, exc_info=True)
            return {"error": "Failed to update preference"}, 500

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
            return {"error": ERR_MISSING_REQUIRED_PARAMS}, 400

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
            return {"error": ERR_MISSING_REQUIRED_PARAMS}, 400

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

    def _get_preferences_from_storage(
        self,
        athlete_id: str,
        status: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """Fetch preferences from AgentPreferences table."""
        client = self.table_storage._get_table_client(  # pylint: disable=protected-access
            "AgentPreferences"
        )

        query = f"PartitionKey eq '{athlete_id}'"
        if status:
            query += f" and status eq '{status}'"

        try:
            entities = client.query_entities(query, results_per_page=limit)
            preference_items = []
            legacy_entity = None

            for entity in entities:
                if entity.get("RowKey") == "preferences":
                    legacy_entity = entity
                else:
                    preference_items.append(
                        self._entity_to_preference_dict(entity)
                    )

            if preference_items:
                preference_items = self._sort_preferences(preference_items)
                return preference_items[:limit]

            if legacy_entity and status in (None, "active"):
                legacy_prefs = self._entity_to_legacy_preferences_dict(
                    legacy_entity
                )
                return self._legacy_preferences_to_items(legacy_prefs)

            return []
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error querying preferences: %s", exc)
            return []

    def _store_preference(self, preference: AgentPreference):
        """Store preference to AgentPreferences table."""
        client = self.table_storage._get_table_client(  # pylint: disable=protected-access
            "AgentPreferences"
        )

        entity = {
            "PartitionKey": preference.athlete_id,
            "RowKey": preference.preference_id,
            "category": preference.category,
            "summary": preference.summary,
            "details": preference.details,
            "priority": preference.priority,
            "status": preference.status,
            "created_at": preference.created_at,
            "updated_at": preference.updated_at
        }

        client.upsert_entity(entity)

    def _update_preference_in_storage(
        self,
        athlete_id: str,
        preference_id: str,
        updates: Dict[str, Any]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Update preference fields in storage."""
        client = self.table_storage._get_table_client(  # pylint: disable=protected-access
            "AgentPreferences"
        )

        try:
            entity = client.get_entity(
                partition_key=athlete_id,
                row_key=preference_id
            )
            for key, value in updates.items():
                entity[key] = value
            entity["updated_at"] = datetime.now(timezone.utc).isoformat()
            client.update_entity(entity)
            return True, self._entity_to_preference_dict(entity)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error updating preference: %s", exc)
            return False, None

    def _get_active_preferences_from_storage(
        self,
        athlete_id: str,
        limit: int = 10
    ) -> List[Dict]:
        """Fetch active preferences from AgentPreferences table."""
        return self._get_preferences_from_storage(
            athlete_id=athlete_id,
            status="active",
            limit=limit
        )

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
    def _entity_to_legacy_preferences_dict(entity: Dict) -> Dict:
        """Convert legacy preferences entity to preferences dictionary."""
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
    def _entity_to_preference_dict(entity: Dict) -> Dict:
        """Convert preference entity to preference dictionary."""
        return {
            "athlete_id": entity.get("PartitionKey"),
            "preference_id": entity.get("RowKey"),
            "category": entity.get("category"),
            "summary": entity.get("summary"),
            "details": entity.get("details"),
            "priority": entity.get("priority", "normal"),
            "status": entity.get("status", "active"),
            "created_at": entity.get("created_at"),
            "updated_at": entity.get("updated_at")
        }

    @staticmethod
    def _sort_preferences(preferences: List[Dict]) -> List[Dict]:
        """Sort preferences by priority then created_at."""
        priority_order = {"high": 0, "normal": 1, "low": 2}
        preferences.sort(
            key=lambda x: (
                priority_order.get(x.get("priority", "normal"), 1),
                x.get("created_at", "")
            )
        )
        return preferences

    @staticmethod
    def _legacy_preferences_to_items(legacy: Dict) -> List[Dict]:
        """Convert legacy single-record preferences into list items."""
        items = []
        updated_at = legacy.get("updated_at") or datetime.now(timezone.utc).isoformat()

        def add_item(category: str, summary: str, details: Optional[str] = None):
            items.append({
                "athlete_id": legacy.get("athlete_id"),
                "preference_id": f"legacy-{category}",
                "category": category,
                "summary": summary,
                "details": details,
                "priority": "normal",
                "status": "active",
                "created_at": updated_at,
                "updated_at": updated_at
            })

        if legacy.get("current_goal"):
            add_item("current_goal", legacy["current_goal"])
        if legacy.get("training_phase"):
            add_item("training_phase", legacy["training_phase"])
        if legacy.get("preferred_sports"):
            sports = ", ".join(legacy["preferred_sports"])
            add_item("preferred_sports", sports)
        if legacy.get("ftp_test_frequency_weeks"):
            add_item(
                "ftp_test_frequency_weeks",
                f"FTP testing every {legacy['ftp_test_frequency_weeks']} weeks"
            )
        if legacy.get("last_ftp_test_date"):
            add_item(
                "last_ftp_test_date",
                f"Last FTP test: {legacy['last_ftp_test_date']}"
            )
        if legacy.get("notes"):
            add_item("notes", legacy["notes"])

        return items

    @staticmethod
    def _get_preference_summary(preferences: List[Dict], categories: set) -> Optional[str]:
        """Return the first matching preference summary for category set."""
        for pref in preferences:
            if pref.get("category") in categories and pref.get("summary"):
                return pref["summary"]
        return None

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
