#!/usr/bin/env python3
"""
Convert FIT files in the data folder to JSON payloads for Postman testing.

Usage:
    python convert_fit_to_payload.py                    # Convert all FIT files
    python convert_fit_to_payload.py filename.fit       # Convert specific file
"""

import base64
import json
import sys
from pathlib import Path


def convert_fit_to_payload(fit_file: Path) -> Path:
    """Convert a FIT file to a JSON payload."""
    print(f"Converting {fit_file.name}...", end=" ")
    
    with open(fit_file, 'rb') as f:
        content = f.read()
        b64_content = base64.b64encode(content).decode('utf-8')
    
    filename = fit_file.name
    
    payload = {
        "athlete_id": "rob",
        "source_item_id": f"test_{filename.replace('.fit', '')}",
        "source_file_name": filename,
        "source_file_path": f"/Apps/HealthFit/{filename}",
        "source_drive_id": "b!test-drive-id",
        "source_etag": f'"{hash(filename) & 0xFFFFFFFF:08x}"',
        "file_size_bytes": len(content),
        "file_content_b64": b64_content
    }
    
    # Save to JSON file
    output_name = fit_file.parent / f"test_payload_{filename.replace('.fit', '.json')}"
    with open(output_name, 'w', encoding='utf-8') as out:
        json.dump(payload, out, indent=2)
    
    print(f"✓ Created {output_name.name} ({len(content):,} bytes → {len(b64_content):,} base64 chars)")
    return output_name


def main():
    """Main function to convert FIT files to JSON payloads."""
    data_dir = Path(__file__).parent
    
    if len(sys.argv) > 1:
        # Convert specific file
        fit_file = data_dir / sys.argv[1]
        if not fit_file.exists():
            print(f"Error: {fit_file} not found")
            sys.exit(1)
        if fit_file.suffix != '.fit':
            print(f"Error: {fit_file} is not a .fit file")
            sys.exit(1)
        convert_fit_to_payload(fit_file)
    else:
        # Convert all FIT files that don't have payloads
        fit_files = sorted(data_dir.glob('*.fit'))
        
        if not fit_files:
            print("No .fit files found in this directory")
            sys.exit(1)
        
        print(f"Found {len(fit_files)} FIT files\n")
        
        converted = 0
        skipped = 0
        
        for fit_file in fit_files:
            payload_name = data_dir / f"test_payload_{fit_file.name.replace('.fit', '.json')}"
            
            if payload_name.exists():
                print(f"Skipping {fit_file.name} (payload already exists)")
                skipped += 1
            else:
                convert_fit_to_payload(fit_file)
                converted += 1
        
        print(f"\n{'='*60}")
        print(f"Converted: {converted} files")
        print(f"Skipped: {skipped} files (already have payloads)")
        print(f"Total payloads available: {converted + skipped}")


if __name__ == '__main__':
    main()
