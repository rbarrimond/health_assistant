"""Configuration management handler."""

import json
import logging
from datetime import date
from typing import Dict, Tuple, Any

from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.platform.exceptions import ConfigError, StorageError

logger = logging.getLogger(__name__)


class ConfigHandler:
    """Handles physiometrics configuration operations."""

    @staticmethod
    def _history_item(entry: Dict[str, Any]) -> Dict[str, Any]:
        """Build response payload for one config history entry."""
        item = {
            "updated_at_utc": entry.get("updated_at_utc"),
            "effective_date": entry.get("effective_date"),
            "data_source": entry.get("data_source"),
            "heart_rate": {
                "basis": entry.get("heart_rate_basis"),
                "lthr_bpm": entry.get("heart_rate_lthr_bpm"),
                "hr_max_bpm": entry.get("heart_rate_hr_max_bpm"),
                "resting_hr_bpm": entry.get("heart_rate_resting_bpm"),
            },
            "power": {
                "ftp_watts": entry.get("power_ftp_watts"),
            }
        }

        ext_json = entry.get("ext_json")
        if not isinstance(ext_json, str):
            return item

        try:
            parsed_ext = json.loads(ext_json)
        except json.JSONDecodeError:
            return item

        if not isinstance(parsed_ext, dict):
            return item

        athlete_info = parsed_ext.get("athlete_info")
        gear = parsed_ext.get("gear")
        if isinstance(athlete_info, dict):
            item["athlete_info"] = athlete_info
        if isinstance(gear, dict):
            item["gear"] = gear
        return item

    def update_config(self, config_data: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        """Update configuration and persist to storage.

        Args:
            config_data: Configuration dictionary with heart_rate and power sections

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not isinstance(config_data, dict):
            return {"error": "Payload must be a JSON object"}, 400

        try:
            effective_date = config_data.get("as_of")
            if effective_date is not None:
                try:
                    date.fromisoformat(str(effective_date))
                except ValueError:
                    return {
                        "error": "Invalid as_of date; expected YYYY-MM-DD"
                    }, 400

            payload = dict(config_data)
            payload.pop("as_of", None)

            if effective_date is None:
                timestamp = Config.save_physiometrics(payload)
            else:
                timestamp = Config.save_physiometrics(
                    payload,
                    effective_date=str(effective_date),
                )

            hr_cfg = Config.hr_config()
            pwr_cfg = Config.power_config()

            athlete_info = payload.get("athlete_info")
            gear = payload.get("gear")

            logger.info("Configuration updated at %s", timestamp)

            response = {
                "status": "success",
                "message": "Configuration saved to Azure Table Storage",
                "updated_at_utc": timestamp,
                "heart_rate": {
                    "basis": hr_cfg.basis,
                    "lthr_bpm": hr_cfg.lthr_bpm,
                    "hr_max_bpm": hr_cfg.hr_max_bpm,
                    "resting_hr_bpm": hr_cfg.resting_hr_bpm,
                },
                "power": {
                    "ftp_watts": pwr_cfg.ftp_watts,
                }
            }

            if effective_date is not None:
                response["as_of"] = str(effective_date)
            if isinstance(athlete_info, dict):
                response["athlete_info"] = athlete_info
            if isinstance(gear, dict):
                response["gear"] = gear

            return response, 200

        except ConfigError as exc:
            logger.error("Configuration update failed: %s", exc, exc_info=True)
            return {
                "error": "Failed to update configuration",
                "details": str(exc)
            }, 500
        except StorageError as exc:
            logger.error("Error updating config: %s", exc, exc_info=True)
            return {
                "error": "Unexpected error updating configuration",
                "details": str(exc)
            }, 500

    def get_history(self, limit: int = 10) -> Tuple[Dict[str, Any], int]:
        """Get configuration change history.

        Args:
            limit: Maximum number of history entries to return (default 10, max 50)

        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            limit = min(int(limit), 50)  # Cap at 50

            history = Config.get_physiometrics_history(limit=limit)
            result = [self._history_item(entry) for entry in history]

            return {
                "status": "success",
                "count": len(result),
                "history": result
            }, 200

        except (ConfigError, StorageError, ValueError, OSError, KeyError) as exc:
            logger.error("Error retrieving config history: %s", exc, exc_info=True)
            return {
                "error": "Failed to retrieve configuration history",
                "details": str(exc)
            }, 500
