#!/usr/bin/env python3
"""Check if Garmin training data is in ext_json field."""

import os
import sys
import json

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator


def check_garmin_ext_json():
    """Check if training data is in ext_json of Garmin entities."""
    
    storage = StorageCoordinator()
    physiometrics_table = storage.infrastructure.get_table_client("Physiometrics")
    
    # Get one Garmin entity
    entities = list(physiometrics_table.query_entities(
        query_filter="PartitionKey eq 'rob' and data_source eq 'garmin'",
        select=None,
    ))
    
    if not entities:
        print("No Garmin entities found")
        return
    
    entity = entities[0]
    print(f"Checking entity: {entity.get('RowKey')} (PartitionKey: {entity.get('PartitionKey')})")
    print()
    
    ext_json = entity.get("ext_json")
    if not ext_json:
        print("❌ No ext_json field found")
        return
    
    try:
        data = json.loads(ext_json)
        print("✅ ext_json parsed successfully")
        print()
        print("=" * 80)
        print("EXT_JSON STRUCTURE:")
        print("=" * 80)
        print(json.dumps(data, indent=2)[:2000])  # First 2000 chars
        print()
        
        # Check for training metrics in the data
        training_status = data.get("training_status", {})
        summary = data.get("summary", {})
        
        print()
        print("=" * 80)
        print("CHECKING FOR TRAINING DATA:")
        print("=" * 80)
        
        if training_status:
            print("✅ training_status found in ext_json")
            print(f"   Keys: {list(training_status.keys())}")
        else:
            print("❌ No training_status in ext_json")
        
        if summary:
            print("✅ summary found in ext_json")
            stats = summary.get("stats", {})
            if stats:
                print(f"   stats keys: {list(stats.keys())[:10]}")  # First 10 keys
        
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse ext_json: {e}")


if __name__ == "__main__":
    check_garmin_ext_json()
