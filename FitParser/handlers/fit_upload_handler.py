"""Handle FIT file upload and parsing workflow."""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

from FitParser.fit_parser import FitParser, compute_file_hash
from FitParser.table_storage import WorkoutTableStorage

logger = logging.getLogger(__name__)


class FitUploadHandler:
    """Orchestrates FIT file upload → parse → store workflow."""

    def __init__(self, storage: WorkoutTableStorage):
        self.storage = storage

    def handle(self, file_path: str, athlete_id: str) -> Tuple[Optional[Dict], int]:
        """
        Process FIT file upload.

        Args:
            file_path: Path to FIT file
            athlete_id: Athlete identifier

        Returns:
            (WorkoutMetricsModel or None, HTTP status code)
        """
        try:
            # Validate file exists
            if not Path(file_path).exists():
                logger.warning("FIT file not found: %s", file_path)
                return None, 404

            # Parse FIT file
            parser = FitParser(file_path)
            metrics: Dict = parser.parse()

            file_path_obj = Path(file_path)
            file_sha256 = compute_file_hash(file_path)
            source_info = {
                "source_system": "Local",
                "source_file_name": file_path_obj.name,
                "source_file_path": str(file_path_obj),
                "file_size_bytes": file_path_obj.stat().st_size,
                "file_sha256": file_sha256,
            }

            # Store workout and record ingestion state
            workout_id = self.storage.store_workout(
                athlete_id, metrics, source_info
            )
            self.storage.record_ingestion_state(
                athlete_id,
                source_info,
                status="ingested",
                workout_id=workout_id,
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
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Upload failed: %s", exc, exc_info=True)
            return None, 500
