#!/usr/bin/env python
"""Diagnostic script to inspect FIT files from failed ingestions.

Usage:
    python inspect_fit_files.py [--csv PATH] [--ingestion-ids FILE]

This script loads FIT files from blob storage and inspects the manufacturer
field to determine why it's being set to None.
"""

import argparse
import csv
import io
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitdecode

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_csv_ingestion_ids(csv_path: str) -> List[str]:
    """Extract ingestion_ids from IngestionState_filter.csv."""
    ingestion_ids = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("RowKey"):
                    ingestion_ids.append(row["RowKey"])
    except FileNotFoundError:
        logger.error(f"CSV file not found: {csv_path}")
        return []
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error reading CSV: {e}")
        return []

    logger.info(f"Found {len(ingestion_ids)} ingestion IDs in CSV")
    return ingestion_ids


def inspect_fit_file(fit_bytes: bytes) -> Optional[Dict[str, Any]]:
    """Inspect a FIT file's manufacturer field.

    Returns:
        Dict with file_id message details, or None if parsing fails
    """
    try:
        reader = fitdecode.FitReader(io.BytesIO(fit_bytes))

        file_id_info = {}
        for frame in reader:
            if isinstance(frame, fitdecode.FitDataMessage):
                if frame.name == "file_id":
                    for field in frame.fields:
                        file_id_info[field.name] = {
                            "value": field.value,
                            "value_type": type(field.value).__name__,
                            "units": field.units,
                        }
                    logger.info(f"file_id message found: {json.dumps(file_id_info, indent=2, default=str)}")
                    return file_id_info

        if not file_id_info:
            logger.warning("No file_id message found in FIT file")
        return file_id_info if file_id_info else None

    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error parsing FIT file: {e}")
        return None


def analyze_fit_for_diagnosis(fit_bytes: bytes, ingestion_id: str) -> None:
    """Analyze a FIT file and diagnose manufacturer field issues."""
    logger.info(f"\n{'='*70}")
    logger.info(f"Analyzing ingestion_id: {ingestion_id}")
    logger.info(f"{'='*70}")

    file_info = inspect_fit_file(fit_bytes)

    if not file_info:
        logger.warning("Could not extract file_id information")
        return

    manufacturer = file_info.get("manufacturer", {})
    logger.info(f"\nManufacturer field details:")
    logger.info(f"  Value: {manufacturer.get('value')}")
    logger.info(f"  Type: {manufacturer.get('value_type')}")
    logger.info(f"  Units: {manufacturer.get('units')}")

    # Diagnosis
    mfr_value = manufacturer.get("value")
    if mfr_value is None:
        logger.error("⚠️  DIAGNOSIS: manufacturer field is None in the FIT file")
        logger.error("   This indicates the file was exported without manufacturer data")
        logger.error("   Possible causes:")
        logger.error("   - FIT file was created by a third-party tool")
        logger.error("   - FIT file was corrupted during download")
        logger.error("   - Garmin API returned incomplete data")
    else:
        logger.info(f"✓ Manufacturer field present: {mfr_value} (type: {type(mfr_value).__name__})")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Inspect FIT files to diagnose manufacturer field issues"
    )
    parser.add_argument(
        "--csv",
        type=str,
        default="IngestionState_filter.csv",
        help="Path to IngestionState_filter.csv",
    )
    parser.add_argument(
        "--ingestion-ids",
        type=str,
        help="File with ingestion IDs (one per line) to inspect",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Limit number of files to inspect (default: 5)",
    )

    args = parser.parse_args()

    # Get ingestion IDs to inspect
    if args.ingestion_ids:
        with open(args.ingestion_ids, "r", encoding="utf-8") as f:
            ingestion_ids = [line.strip() for line in f if line.strip()]
    else:
        ingestion_ids = parse_csv_ingestion_ids(args.csv)

    if not ingestion_ids:
        logger.error("No ingestion IDs found")
        sys.exit(1)

    logger.info(f"Inspecting up to {args.limit} ingestion IDs")
    logger.info("\nTo actually load FIT bytes from storage, update this script with:")
    logger.info("  1. Azure Storage connection string or Azurite endpoint")
    logger.info("  2. Code to download raw FIT JSON from blob storage")
    logger.info("  3. Conversion of raw FIT JSON back to bytes for fitdecode")
    logger.info("\nFor now, this script demonstrates the analysis structure.")

    # Example: demonstrate with a mock FIT inspection
    logger.info("\nDemonstrating diagnosis approach:")
    logger.info("If manufacturer field is None, it means:")
    logger.info("  - The FIT file's file_id.manufacturer field was not set by the device")
    logger.info("  - This is unusual for Garmin API workouts, which should include it")
    logger.info("  - Possible workaround: default Garmin API workouts to manufacturer=1")


if __name__ == "__main__":
    main()
