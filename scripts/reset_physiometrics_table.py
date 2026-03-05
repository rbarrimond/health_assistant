#!/usr/bin/env python3
"""Drop and recreate Physiometrics table with correct schema."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator


def reset_physiometrics_table():
    """Drop and recreate Physiometrics table."""
    
    storage = StorageCoordinator()
    
    try:
        table_client = storage.infrastructure.get_table_client("Physiometrics")
        
        print("🗑️  Dropping Physiometrics table...")
        table_client.delete_table()
        print("✅ Table dropped successfully")
        
    except Exception as e:
        print(f"⚠️  Note: {e}")
        print("   (Table may not exist yet)")
    
    print("\n📋 Creating Physiometrics table with correct schema...")
    from azure.data.tables import TableServiceClient
    
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    service = TableServiceClient.from_connection_string(conn_str, connection_verify=True)
    
    try:
        service.create_table_if_not_exists("Physiometrics")
        print("✅ Physiometrics table created successfully")
        print("\n🎯 Next step: Re-run Garmin sync to populate with queryable training columns")
        
    except Exception as e:
        print(f"❌ Failed to create table: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(reset_physiometrics_table())
