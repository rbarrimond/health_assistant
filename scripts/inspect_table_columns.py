#!/usr/bin/env python3
"""Inspect actual columns in the Workouts table to verify structure."""

import os
import sys
from collections import Counter

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator


def inspect_workouts_table():
    """Query a few entities from Workouts table and show actual column names."""
    
    storage = StorageCoordinator()
    workouts_table = storage.infrastructure.get_table_client("Workouts")
    
    print("Inspecting Workouts table structure...\n")
    
    # Get a sample of entities
    entities = list(workouts_table.query_entities(
        query_filter="PartitionKey ne ''",
        select=None,  # Get all columns
    ))
    
    if not entities:
        print("No entities found in Workouts table.")
        return
    
    print(f"Found {len(entities)} total entities")
    print("Sampling first 5 entities...\n")
    
    # Collect all column names from sample
    all_columns = Counter()
    for entity in entities[:5]:
        all_columns.update(entity.keys())
    
    # Display first entity keys
    print("=" * 80)
    print("FIRST ENTITY COLUMNS:")
    print("=" * 80)
    first_entity = entities[0]
    for key in sorted(first_entity.keys()):
        value = first_entity[key]
        value_type = type(value).__name__
        value_str = str(value)[:50]  # Truncate long values
        print(f"{key:40s} = {value_str:50s} ({value_type})")
    
    print("\n")
    print("=" * 80)
    print("ALL COLUMNS FOUND (across sample):")
    print("=" * 80)
    for col in sorted(all_columns.keys()):
        count = all_columns[col]
        print(f"{col:40s} (appears in {count}/5 entities)")
    
    # Check for suspicious @type columns
    print("\n")
    print("=" * 80)
    print("CHECKING FOR @type COLUMNS:")
    print("=" * 80)
    type_columns = [col for col in all_columns.keys() if "@type" in col]
    if type_columns:
        print(f"⚠️  WARNING: Found {len(type_columns)} @type columns!")
        for col in sorted(type_columns):
            print(f"  - {col}")
        print("\nThese columns should NOT exist in the table.")
    else:
        print("✅ No @type columns found - table structure is clean.")
    
    # Check for odata metadata columns
    odata_columns = [col for col in all_columns.keys() if col.startswith("odata.") or col in ["Timestamp", "etag"]]
    if odata_columns:
        print("\n")
        print("Azure Table Storage system columns (expected):")
        for col in sorted(odata_columns):
            print(f"  - {col}")


if __name__ == "__main__":
    inspect_workouts_table()
