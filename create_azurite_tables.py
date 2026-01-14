"""Create required Azure Table Storage tables in Azurite.

This script uses the local Azurite emulator connection string and
creates the tables used by the project if they do not already exist.
"""
import json
import os
import sys
from pathlib import Path

from azure.data.tables import TableServiceClient

TABLES = ["Workouts", "WeeklyRollups", "IngestionState"]


def get_connection_string() -> str:
    """Resolve a connection string for Azurite.

    Priority:
    1) AZURE_STORAGE_CONNECTION_STRING env var
    2) local.settings.json Values.AzureWebJobsStorage
    3) Fallback to "UseDevelopmentStorage=true"
    """
    cs = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if cs:
        return cs

    # Try local.settings.json (Azure Functions local dev convention)
    settings_path = Path("local.settings.json")
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text())
            values = data.get("Values", {})
            cs_from_file = values.get("AzureWebJobsStorage")
            if cs_from_file:
                return cs_from_file
        except Exception:
            pass

    # Default Azurite dev connection string
    return "UseDevelopmentStorage=true"


def main() -> int:
    conn_str = get_connection_string()
    print(f"Using connection string: {conn_str}")

    try:
        # For local Azurite with self-signed certs, disable TLS verification.
        # This is safe for local development only.
        service = TableServiceClient.from_connection_string(conn_str, connection_verify=False)
    except Exception as e:
        print(f"Failed to create TableServiceClient: {e}")
        return 1

    success = True
    for name in TABLES:
        try:
            service.create_table_if_not_exists(name)
            print(f"✔ Table ready: {name}")
        except Exception as e:
            print(f"✖ Error creating table {name}: {e}")
            success = False

    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
