"""Configuration management handler."""

import json
import logging
from typing import Dict, Tuple, Any

from TrainingAnalyticsPlatform.config import Config

logger = logging.getLogger(__name__)


class ConfigHandler:
    """Handles physiometrics configuration operations."""

    def reload_config(self) -> Tuple[Dict[str, Any], int]:
        """Reload configuration from disk/storage.

        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            config_data = Config.load_physiometrics(force_reload=True)

            if config_data is None:
                logger.warning("Physiometrics file not found at %s",
                               Config.physiometrics_file())
                return {
                    "error": "Physiometrics file not found",
                    "path": str(Config.physiometrics_file())
                }, 404

            hr_cfg = Config.hr_config()
            pwr_cfg = Config.power_config()

            return {
                "status": "success",
                "message": "Configuration reloaded from disk",
                "heart_rate": {
                    "basis": hr_cfg.basis,
                    "lthr_bpm": hr_cfg.lthr_bpm,
                    "hr_max_bpm": hr_cfg.hr_max_bpm,
                    "resting_hr_bpm": hr_cfg.resting_hr_bpm,
                },
                "power": {
                    "ftp_watts": pwr_cfg.ftp_watts,
                }
            }, 200

        except json.JSONDecodeError as exc:
            logger.error("JSON parsing error in physiometrics file: %s", exc)
            return {
                "error": "Invalid JSON in physiometrics file",
                "details": str(exc)
            }, 500
        except (OSError, IOError, ValueError, KeyError) as exc:
            logger.error("Error reloading config: %s", exc, exc_info=True)
            return {
                "error": "Failed to reload configuration",
                "details": str(exc)
            }, 500

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
            timestamp = Config.save_physiometrics(config_data)

            hr_cfg = Config.hr_config()
            pwr_cfg = Config.power_config()

            logger.info("Configuration updated at %s", timestamp)

            return {
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
            }, 200

        except ValueError as exc:
            logger.error("Validation error updating config: %s", exc)
            return {
                "error": "Failed to update configuration",
                "details": str(exc)
            }, 500
        except (OSError, IOError, KeyError) as exc:
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

            result = []
            for entry in history:
                result.append({
                    "updated_at_utc": entry.get("RowKey"),
                    "heart_rate": {
                        "basis": entry.get("heart_rate_basis"),
                        "lthr_bpm": entry.get("heart_rate_lthr_bpm"),
                        "hr_max_bpm": entry.get("heart_rate_hr_max_bpm"),
                        "resting_hr_bpm": entry.get("heart_rate_resting_bpm"),
                    },
                    "power": {
                        "ftp_watts": entry.get("power_ftp_watts"),
                    }
                })

            return {
                "status": "success",
                "count": len(result),
                "history": result
            }, 200

        except (ValueError, OSError, KeyError) as exc:
            logger.error("Error retrieving config history: %s", exc, exc_info=True)
            return {
                "error": "Failed to retrieve configuration history",
                "details": str(exc)
            }, 500
