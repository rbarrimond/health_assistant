"""Handle FIT file upload and parsing workflow."""

import logging
from pathlib import Path
from typing import Optional, Tuple

from FitParser.fit_parser import FitParser
from FitParser.models import WorkoutMetricsModel
from FitParser.table_storage import WorkoutTableStorage

logger = logging.getLogger(__name__)


class FitUploadHandler:
    """Orchestrates FIT file upload → parse → store workflow."""

    def __init__(self, storage: WorkoutTableStorage):
        self.storage = storage

    def handle(self, file_path: str, athlete_id: str) -> Tuple[Optional[WorkoutMetricsModel], int]:
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
            metrics: WorkoutMetricsModel = parser.parse()

            # Store metrics
            self.storage.upsert_metrics(athlete_id, metrics)

            logger.info(
                "FIT uploaded: athlete=%s, sport=%s, duration=%s sec",
                athlete_id,
                metrics.session.sport,
                metrics.session.duration_sec,
            )
            return metrics, 201

        except ValueError as exc:
            logger.warning("Invalid FIT file: %s", exc)
            return None, 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Upload failed: %s", exc, exc_info=True)
            return None, 500
