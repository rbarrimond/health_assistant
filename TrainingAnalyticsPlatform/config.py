"""Configuration and environment utilities.

This module supports three configuration sources (in order of precedence):
1) Azure Table Storage (Physiometrics table) - recommended for production
2) Filesystem JSON file (`config/physiometrics.json`)
3) Environment variables - deployment overrides

Ingestion MUST snapshot the relevant physiometrics into each workout record, so
configuration only needs to represent *current truth*.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


def _as_int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _as_float(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


@dataclass(frozen=True)
class HeartRateConfig:
    """Heart rate zone configuration.

    Attributes:
        basis: Zone calculation method (HRmax, LTHR, or HRR)
        lthr_bpm: Lactate Threshold Heart Rate in BPM
        hr_max_bpm: Maximum Heart Rate in BPM
        resting_hr_bpm: Resting Heart Rate in BPM
        zones: Zone definitions with lower/upper percentages
    """
    basis: str
    lthr_bpm: Optional[int]
    hr_max_bpm: Optional[int]
    resting_hr_bpm: Optional[int]
    zones: Dict[str, Dict[str, Any]]


@dataclass(frozen=True)
class PowerConfig:
    """Power zone configuration.

    Attributes:
        ftp_watts: Functional Threshold Power in watts
        zones: Zone definitions with lower/upper percentages
    """
    ftp_watts: Optional[int]
    zones: Dict[str, Dict[str, Any]]


class Config:
    """Configuration loaded from physiometrics.json with env var fallback.

    Design intent:
    - `physiometrics.json` represents *current athlete truth*.
    - Env vars can override for deployments / experiments.
    - Ingestion snapshots all relevant values into workout rows.
    """

    # Azure Storage
    AZURE_STORAGE_CONNECTION_STRING = os.getenv("AzureWebJobsStorage")
    AZURE_STORAGE_ACCOUNT_URL = os.getenv("AZURE_STORAGE_ACCOUNT_URL")

    # OneDrive
    ONEDRIVE_FOLDER_PATH = os.getenv("ONEDRIVE_FOLDER_PATH", "/Apps/HealthFit")

    # Athlete
    DEFAULT_ATHLETE_ID = os.getenv("DEFAULT_ATHLETE_ID", "rob")

    # Config file discovery
    # You can override with PHYSIOMETRICS_PATH to point anywhere.
    PHYSIOMETRICS_PATH = os.getenv("PHYSIOMETRICS_PATH")

    _physiometrics_cache: Optional[Dict[str, Any]] = None
    _table_storage_client = None

    # Allow imports inside methods to avoid circular dependencies.
    # pylint: disable=import-outside-toplevel
    @staticmethod
    def _get_table_storage():
        """Lazy-load table storage client."""
        # Avoid circular imports and only initialize if storage is needed
        if Config._table_storage_client is None:
            try:
                from .table_storage import WorkoutTableStorage
                Config._table_storage_client = WorkoutTableStorage()
            except (ImportError, ValueError, OSError) as e:
                logger = logging.getLogger(__name__)
                logger.debug(
                    "Table storage not available; "
                    "will use filesystem config: %s", e
                )
                Config._table_storage_client = False  # Sentinel: unavailable
        return Config._table_storage_client if Config._table_storage_client is not False else None

    @staticmethod
    def _repo_root() -> Path:
        """Return repository root path.

        Config.py lives in TrainingAnalyticsPlatform/. Default config/ is at repo root.
        """
        return Path(__file__).resolve().parents[1]

    @classmethod
    def physiometrics_file(cls) -> Path:
        """Return path to physiometrics.json configuration file."""
        if cls.PHYSIOMETRICS_PATH:
            return Path(cls.PHYSIOMETRICS_PATH).expanduser().resolve()
        return (cls._repo_root() / "config" / "physiometrics.json").resolve()

    @classmethod
    def load_physiometrics(cls, *, force_reload: bool = False) -> Optional[Dict[str, Any]]:
        """Load physiometrics configuration.

        Precedence:
        1) Azure Table Storage (Physiometrics table)
        2) Filesystem JSON file (config/physiometrics.json)
        3) Returns None if neither available
        """
        if cls._physiometrics_cache is not None and not force_reload:
            return cls._physiometrics_cache

        # Try Azure Table Storage first
        athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")
        storage = cls._get_table_storage()
        if storage:
            try:
                table_data = storage.get_physiometrics(athlete_id)
                if table_data:
                    cls._physiometrics_cache = table_data
                    return table_data
            except (ValueError, OSError, KeyError) as e:
                logger = logging.getLogger(__name__)
                logger.debug(
                    "Failed to load physiometrics from table storage: %s", e
                )
                # Fall through to filesystem

        # Fallback to filesystem
        path = cls.physiometrics_file()
        if not path.exists():
            cls._physiometrics_cache = None
            return None

        cls._physiometrics_cache = json.loads(path.read_text(encoding="utf-8"))
        return cls._physiometrics_cache

    @classmethod
    def save_physiometrics(cls, physiometrics_data: Dict[str, Any]) -> str:
        """Save physiometrics configuration to Azure Table Storage.

        Args:
            physiometrics_data: Complete physiometrics configuration dict

        Returns:
            Timestamp of the update (ISO format)

        Raises:
            ValueError: If table storage is not available or save fails
        """
        storage = cls._get_table_storage()
        if not storage:
            raise ValueError(
                "Table storage not available. "
                "Cannot save configuration to Azure Tables."
            )

        athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")
        try:
            timestamp = storage.store_physiometrics(athlete_id, physiometrics_data)
            # Clear cache so next load gets fresh data
            cls._physiometrics_cache = None
            return timestamp
        except (ValueError, OSError, KeyError) as e:
            logger = logging.getLogger(__name__)
            logger.error("Failed to save physiometrics to table storage: %s", e)
            raise ValueError(f"Failed to save configuration: {str(e)}") from e

    @classmethod
    def get_physiometrics_history(cls, limit: int = 10) -> list:
        """Get physiometrics configuration history from Azure Table.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of historical config entries (newest first)
        """
        storage = cls._get_table_storage()
        if not storage:
            return []

        athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")
        try:
            return storage.list_physiometrics_history(athlete_id, limit=limit)
        except (ValueError, OSError, KeyError) as e:
            logger = logging.getLogger(__name__)
            logger.warning("Failed to retrieve history: %s", e)
            return []
    # Heart rate configuration
    # -------------------------

    @classmethod
    def hr_config(cls) -> HeartRateConfig:
        """Return heart-rate configuration.

        Precedence:
        1) Env vars (deployment overrides)
        2) physiometrics.json
        3) hard defaults
        """
        env_basis = os.getenv("HR_ZONE_BASIS")
        env_ref = _as_int(os.getenv("HR_ZONE_REFERENCE_BPM"))
        env_rest = _as_int(os.getenv("HR_RESTING_BPM"))

        pm = cls.load_physiometrics() or {}
        hr = pm.get("heart_rate", {}) if isinstance(pm, dict) else {}

        # Determine basis: env override, config file, or default
        basis = (env_basis or hr.get("basis") or "HRmax").strip()

        # Determine reference values based on basis
        lthr_bpm = cls._resolve_lthr_bpm(env_basis, env_ref, basis, hr)
        hr_max_bpm = cls._resolve_hr_max_bpm(env_basis, env_ref, basis, hr)
        resting_hr_bpm = env_rest or _as_int(hr.get("resting_hr_bpm")) or 60

        zones = cls._resolve_hr_zones(hr)

        return HeartRateConfig(
            basis=basis,
            lthr_bpm=lthr_bpm,
            hr_max_bpm=hr_max_bpm,
            resting_hr_bpm=resting_hr_bpm,
            zones=zones,
        )

    @staticmethod
    def _resolve_lthr_bpm(
            env_basis: Optional[str],
            env_ref: Optional[int],
            basis: str,
            hr: Dict[str, Any]) -> Optional[int]:
        """Resolve LTHR value from environment or config."""
        if env_basis == "LTHR" and env_ref is not None:
            return env_ref
        if env_basis is None and basis == "LTHR" and env_ref is not None:
            return env_ref
        return _as_int(hr.get("lthr_bpm"))

    @staticmethod
    def _resolve_hr_max_bpm(
            env_basis: Optional[str],
            env_ref: Optional[int],
            basis: str,
            hr: Dict[str, Any]) -> Optional[int]:
        """Resolve HR max value from environment or config."""
        if env_basis == "HRmax" and env_ref is not None:
            return env_ref
        if env_basis is None and basis == "HRmax" and env_ref is not None:
            return env_ref
        return _as_int(hr.get("hr_max_bpm"))

    @staticmethod
    def _resolve_hr_zones(hr: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Resolve HR zone definitions from config or use defaults."""
        zones_block = (
            hr.get("zones", {})
            if isinstance(hr.get("zones", {}), dict)
            else {}
        )
        zones = (
            zones_block.get("zones")
            if isinstance(zones_block.get("zones"), dict)
            else zones_block
        )
        if not isinstance(zones, dict) or not zones:
            zones = {
                "z1": {
                    "label": "Recovery",
                    "lower_pct": 0.00,
                    "upper_pct": 0.81,
                },
                "z2": {
                    "label": "Endurance",
                    "lower_pct": 0.81,
                    "upper_pct": 0.89,
                },
                "z3": {"label": "Tempo", "lower_pct": 0.90, "upper_pct": 0.93},
                "z4": {
                    "label": "Threshold",
                    "lower_pct": 0.94,
                    "upper_pct": 0.99,
                },
                "z5": {
                    "label": "VO2+/Ana",
                    "lower_pct": 1.00,
                    "upper_pct": 1.20,
                },
            }
        return zones

    @classmethod
    def power_config(cls) -> PowerConfig:
        """Return power configuration.

        Precedence:
        1) Env vars (deployment overrides)
        2) physiometrics.json
        3) hard defaults
        """
        env_ftp = _as_int(os.getenv("DEFAULT_FTP"))

        pm = cls.load_physiometrics() or {}
        pwr = pm.get("power", {}) if isinstance(pm, dict) else {}

        ftp_watts = env_ftp or _as_int(pwr.get("ftp_watts")) or 250

        zones = cls._resolve_power_zones(pwr)

        return PowerConfig(
            ftp_watts=ftp_watts,
            zones=zones,
        )

    @staticmethod
    def _resolve_power_zones(pwr: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Resolve power zone definitions from config or use defaults."""
        zones_block = (
            pwr.get("zones", {})
            if isinstance(pwr.get("zones", {}), dict)
            else {}
        )
        zones = (
            zones_block.get("zones")
            if isinstance(zones_block.get("zones"), dict)
            else zones_block
        )
        if not isinstance(zones, dict) or not zones:
            zones = {
                "z1": {
                    "label": "Active Recovery",
                    "lower_pct": 0.00,
                    "upper_pct": 0.55,
                },
                "z2": {
                    "label": "Endurance",
                    "lower_pct": 0.56,
                    "upper_pct": 0.75,
                },
                "z3": {
                    "label": "Tempo",
                    "lower_pct": 0.76,
                    "upper_pct": 0.90,
                },
                "z4": {
                    "label": "Threshold",
                    "lower_pct": 0.91,
                    "upper_pct": 1.05,
                },
                "z5": {"label": "VO2max", "lower_pct": 1.06, "upper_pct": 1.20},
                "z6": {
                    "label": "Anaerobic",
                    "lower_pct": 1.21,
                    "upper_pct": 1.50,
                },
                "z7": {
                    "label": "Neuromuscular",
                    "lower_pct": 1.51,
                    "upper_pct": 3.00,
                },
            }
        return zones

    # -------------------
    # Validation
    # -------------------

    @staticmethod
    def validate() -> None:
        """Validate required configuration is present."""
        if not Config.AZURE_STORAGE_CONNECTION_STRING and not Config.AZURE_STORAGE_ACCOUNT_URL:
            raise ValueError(
                "Must set AzureWebJobsStorage or AZURE_STORAGE_ACCOUNT_URL environment variable"
            )

        # Optional but strongly recommended: physiometrics file present.
        # If absent, env var defaults will be used.
        # We do not hard-fail because local dev / CI may not have it.
        _ = Config.load_physiometrics(force_reload=False)
