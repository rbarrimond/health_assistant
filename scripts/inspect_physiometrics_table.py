#!/usr/bin/env python3
"""Inspect actual columns in the Physiometrics table to verify structure."""

import os
import sys
from collections import Counter

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator


def inspect_physiometrics_table():
    """Query entities from Physiometrics table and show actual column names."""
    
    storage = StorageCoordinator()
    
    try:
        physiometrics_table = storage.infrastructure.get_table_client("Physiometrics")
    except Exception as e:
        print(f"❌ ERROR: Could not get Physiometrics table client: {e}")
        return
    
    print("Inspecting Physiometrics table structure...\n")
    
    # Get all entities
    try:
        entities = list(physiometrics_table.query_entities(
            query_filter="PartitionKey ne ''",
            select=None,  # Get all columns
        ))
    except Exception as e:
        print(f"❌ ERROR: Could not query Physiometrics table: {e}")
        return
    
    if not entities:
        print("❌ No entities found in Physiometrics table.")
        print("   → This means the sync succeeded but no data was actually stored.")
        print("   → Likely cause: Table auto-created with wrong structure.")
        return
    
    print(f"✅ Found {len(entities)} total entities in Physiometrics table")
    
    # Check for Garmin data sources
    garmin_entities = [e for e in entities if e.get("data_source") == "garmin"]
    print(f"✅ Found {len(garmin_entities)} Garmin-sourced entities")
    
    if garmin_entities:
        print("\nGarmin entity dates:")
        for entity in sorted(garmin_entities, key=lambda e: e.get("RowKey", "")):
            print(f"  - {entity.get('RowKey')} (PartitionKey: {entity.get('PartitionKey')})")
    
    print("\n")
    print("=" * 80)
    print("SAMPLING FIRST ENTITY:")
    print("=" * 80)
    
    # Use first Garmin entity if available, otherwise first entity
    sample_entity = garmin_entities[0] if garmin_entities else entities[0]
    
    for key in sorted(sample_entity.keys()):
        value = sample_entity[key]
        value_type = type(value).__name__
        value_str = str(value)[:60] if value is not None else "None"
        print(f"{key:45s} = {value_str:60s} ({value_type})")
    
    # Collect all column names
    all_columns = Counter()
    for entity in entities:
        all_columns.update(entity.keys())
    
    print("\n")
    print("=" * 80)
    print(f"ALL COLUMNS FOUND (across {len(entities)} entities):")
    print("=" * 80)
    for col in sorted(all_columns.keys()):
        count = all_columns[col]
        print(f"{col:45s} (appears in {count}/{len(entities)} entities)")
    
    # Check for expected training metrics
    print("\n")
    print("=" * 80)
    print("CHECKING FOR GARMIN TRAINING METRICS:")
    print("=" * 80)
    expected_training_metrics = [
        "training_load",
        "training_effect_aerobic",
        "training_effect_anaerobic",
        "training_stress_score",
        "training_stress_balance",
        "atp_probability",
        "recovery_time_minutes",
        "lactate_threshold_hr_bpm",
        "cycling_vo2max_ml_kg_min",
        "running_vo2max_ml_kg_min",
        "power_ftp_watts",
    ]
    
    missing_metrics = []
    found_metrics = []
    
    for metric in expected_training_metrics:
        if metric in all_columns:
            found_metrics.append(metric)
            # Check if any non-null values exist
            non_null_count = sum(1 for e in entities if e.get(metric) is not None)
            print(f"✅ {metric:45s} (non-null in {non_null_count}/{len(entities)} entities)")
        else:
            missing_metrics.append(metric)
            print(f"❌ {metric:45s} (MISSING)")
    
    print("\n")
    print("=" * 80)
    print("SUMMARY:")
    print("=" * 80)
    print(f"Total entities: {len(entities)}")
    print(f"Garmin entities: {len(garmin_entities)}")
    print(f"Expected training metrics found: {len(found_metrics)}/{len(expected_training_metrics)}")
    
    if missing_metrics:
        print(f"\n⚠️  WARNING: Missing {len(missing_metrics)} expected training metrics:")
        for metric in missing_metrics:
            print(f"   - {metric}")
        print("\n   → Table may have been auto-created with incomplete schema")
        print("   → Recommend: Drop table, re-run create_azurite_tables.py, re-sync")
    else:
        print("\n✅ All expected training metrics are present!")
    
    # Check if any Garmin entities have non-null training data
    if garmin_entities:
        print("\n")
        print("=" * 80)
        print("CHECKING GARMIN DATA POPULATION:")
        print("=" * 80)
        
        sample_garmin = garmin_entities[0]
        populated_metrics = {
            k: v for k, v in sample_garmin.items()
            if k in expected_training_metrics and v is not None
        }
        
        if populated_metrics:
            print(f"✅ Sample Garmin entity has {len(populated_metrics)} populated training metrics:")
            for k, v in populated_metrics.items():
                print(f"   {k}: {v}")
        else:
            print("❌ Sample Garmin entity has NO populated training metrics")
            print("   → Data was stored but training metrics are all NULL")
            print("   → Check adapter logic and source API responses")


if __name__ == "__main__":
    inspect_physiometrics_table()
