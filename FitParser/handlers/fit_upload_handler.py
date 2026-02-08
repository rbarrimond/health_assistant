"""Handle FIT file upload and parsing workflow."""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

from FitParser.exceptions import FitAdapterError, WorkoutTypeResolutionError
from FitParser.fit_parser import compute_file_hash
from FitParser.handlers.ingestion_base import IngestionHandlerBase

logger = logging.getLogger(__name__)


class FitUploadHandler(IngestionHandlerBase):
    """Orchestrates FIT file upload → parse → store workflow."""

    def handle(
        self,
        file_path: str,
        athlete_id: str,
        source_file_name: Optional[str] = None,
        source_info: Optional[Dict] = None
    ) -> Tuple[Optional[Dict], int]:
        """
        Process FIT file upload.

        Args:
            file_path: Path to FIT file
            athlete_id: Athlete identifier
            source_file_name: Original filename from source system
            source_info: Full source metadata dict from request/sync

        Returns:
            (WorkoutMetricsModel or None, HTTP status code)
        """
        try:
            # Validate file exists
            if not Path(file_path).exists():
                logger.warning("FIT file not found: %s", file_path)
                return None, 404

            file_path_obj = Path(file_path)
            file_sha256 = compute_file_hash(file_path)

            # Use provided source_info or build default
            if source_info:
                # Merge with computed file hash if not provided
                if "file_sha256" not in source_info or not source_info["file_sha256"]:
                    source_info["file_sha256"] = file_sha256
                if source_file_name:
                    source_info.setdefault("source_file_name", source_file_name)
                final_source_info = source_info
            else:
                final_source_info = {
                    "source_system": "Local",
                    "source_file_name": source_file_name or file_path_obj.name,
                    "source_file_path": str(file_path_obj),
                    "file_size_bytes": file_path_obj.stat().st_size,
                    "file_sha256": file_sha256,
                }

            skipped, _ = self._skip_if_unchanged(athlete_id, final_source_info)
            if skipped:
                logger.info(
                    "Skipping already ingested FIT: athlete=%s, file=%s",
                    athlete_id,
                    final_source_info.get("source_file_name"),
                )
                return None, 200

            metrics, _ = self._parse_and_store(
                athlete_id, file_path, final_source_info
            )

            logger.info(
                "FIT uploaded: athlete=%s, sport=%s, duration=%s sec",
                athlete_id,
                metrics.get("sport"),
                metrics.get("duration_sec"),
            )
            return metrics, 201

        except ValueError as exc:
            logger.warning("Invalid FIT file: %s", exc)
            return None, 400
        except FitAdapterError as exc:
            logger.warning("FIT adapter failed: %s", exc)
            return None, 400
        except WorkoutTypeResolutionError as exc:
            logger.error("Workout type resolution failed: %s", exc)
            return None, 500
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Upload failed: %s", exc, exc_info=True)
            return None, 500
