"""
This script processes FIT files and converts them to JSON format.
It is used for extracting workout data and saving it in a structured format.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from TrainingAnalyticsPlatform.ingestion.fit_message_utils import load_fit_messages


def safe_value(field: Any) -> dict[str, Any]:
    """Return decoded values without raw binary fields."""
    try:
        return {
            "value": getattr(field, "value", None),
            "units": getattr(field, "units", None),
        }
    except Exception as e:
        raise RuntimeError("An error occurred while processing the FIT file") from e


def dump_fit_to_json(fit_path, output_path):
    """Dumps all messages from a FIT file to a JSON file."""
    messages, _ = load_fit_messages(fit_path)

    all_messages = []
    message_index = defaultdict(int)

    for message in messages:
        msg_type = message.get("name", "unknown")
        fields_dict = message.get("fields", {})

        message_index[msg_type] += 1

        msg_dict = {
            "message_type": msg_type,
            "message_index": message_index[msg_type],
            "fields": {},
        }

        for field_name, field in fields_dict.items():
            msg_dict["fields"][field_name] = safe_value(field)

        all_messages.append(msg_dict)

    metadata = {
        "source_file": fit_path,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "message_counts": dict(message_index),
        "total_messages": len(all_messages),
    }

    output = {
        "metadata": metadata,
        "messages": all_messages,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
        f.write("\n")

    print(f"Exported {len(all_messages)} messages to {output_path}")


def process_fit_file(file_path, output_path):
    """
    Processes a FIT file and writes the extracted data to a JSON file.

    Args:
        file_path (str): Path to the FIT file to process.
        output_path (str): Path to the output JSON file.

    Returns:
        None
    """
    dump_fit_to_json(file_path, output_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dump all FIT messages to JSON.")
    parser.add_argument("fit_path", help="Path to input FIT file")
    parser.add_argument(
        "--output",
        help="Output JSON path",
        default="fit_dump.json"
    )

    args = parser.parse_args()

    dump_fit_to_json(args.fit_path, args.output)
