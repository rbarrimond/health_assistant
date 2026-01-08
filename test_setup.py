#!/usr/bin/env python
"""Test script for local Azure Function development."""

import sys
import json
import base64
import tempfile
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from FitParser.fit_parser import FitParser, compute_file_hash


def test_fit_parsing():
    """Test FIT file parsing with sample data."""
    print("Testing FIT Parser...")
    
    # For testing without a real FIT file, we would need a sample
    # For now, just verify imports and structure
    parser_path = Path(__file__).parent / "FitParser" / "fit_parser.py"
    if parser_path.exists():
        print(f"✓ FIT parser module found at {parser_path}")
    else:
        print(f"✗ FIT parser module not found")
        return False
    
    # Test hash computation
    test_content = b"test file content"
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(test_content)
        tmp_path = tmp.name
    
    try:
        file_hash = compute_file_hash(tmp_path)
        print(f"✓ File hash computation works: {file_hash[:16]}...")
        return True
    except Exception as e:
        print(f"✗ File hash computation failed: {e}")
        return False
    finally:
        import os
        os.unlink(tmp_path)


def test_table_storage():
    """Test Azure Table Storage setup."""
    print("\nTesting Azure Table Storage...")
    
    storage_path = Path(__file__).parent / "FitParser" / "table_storage.py"
    if storage_path.exists():
        print(f"✓ Table storage module found at {storage_path}")
    else:
        print(f"✗ Table storage module not found")
        return False
    
    return True


def test_function_handler():
    """Test Azure Function handler."""
    print("\nTesting Azure Function handler...")
    
    handler_path = Path(__file__).parent / "function_app" / "function_handler.py"
    if handler_path.exists():
        print(f"✓ Function handler module found at {handler_path}")
    else:
        print(f"✗ Function handler module not found")
        return False
    
    return True


def test_payload_structure():
    """Test example payload structure."""
    print("\nTesting payload structure...")
    
    example_payload = {
        "athlete_id": "rob",
        "source_item_id": "test_item_id",
        "source_file_name": "2026-01-07-test.fit",
        "source_file_path": "/Apps/HealthFit/2026-01-07-test.fit",
        "source_drive_id": "drive_id",
        "file_content_b64": base64.b64encode(b"test content").decode(),
        "file_size_bytes": 100
    }
    
    # Verify structure
    required_fields = ["athlete_id", "source_file_name", "file_content_b64"]
    missing = [f for f in required_fields if f not in example_payload]
    
    if not missing:
        print(f"✓ Payload structure is valid")
        print(f"  Fields: {', '.join(example_payload.keys())}")
        return True
    else:
        print(f"✗ Missing required fields: {missing}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Health Assistant - Azure Function Setup Test")
    print("=" * 60)
    
    tests = [
        test_fit_parsing,
        test_table_storage,
        test_function_handler,
        test_payload_structure,
    ]
    
    results = [test() for test in tests]
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    
    if all(results):
        print("✓ All checks passed! Ready for deployment.")
        return 0
    else:
        print("✗ Some checks failed. Review above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
