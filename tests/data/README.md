# Test Data Files

This directory contains real FIT workout files and their corresponding JSON payloads for testing the Health Assistant function.

## Real FIT Files

| Filename | Date | Sport | Source | Size | Notes |
|----------|------|-------|--------|------|-------|
| `2026-01-04-163358-Functional Strength Training-Robert's Apple Watch Ultra 3.fit` | Jan 4 | Strength | Apple Watch | 11 KB | ✓ Has JSON payload |
| `2026-01-06-220813-Indoor Cycling-HealthFit.fit` | Jan 6 | Cycling | HealthFit | ? | - |
| `2026-01-07-142711-Outdoor Walking-Robert's Apple Watch Ultra 3.fit` | Jan 7 | Walking | Apple Watch | ? | - |
| `2026-01-07-192805-Functional Strength Training-Robert's Apple Watch Ultra 3.fit` | Jan 7 | Strength | Apple Watch | ? | - |
| `2026-01-08-224701-Indoor Cycling-HealthFit.fit` | Jan 8 | Cycling | HealthFit | ? | - |
| `2026-01-10-203100-Functional Strength Training-Robert's Apple Watch Ultra 3.fit` | Jan 10 | Strength | Apple Watch | ? | - |
| `2026-01-10-211457-Indoor Cycling-RunGap.fit` | Jan 10 | Cycling | RunGap | 52 KB | ✓ Has JSON payload |
| `2026-01-12-183000-Indoor Cycling-RunGap.fit` | Jan 12 | Cycling | RunGap | 121 KB | ✓ Has JSON payload |

## Pre-Generated JSON Payloads

Three JSON payloads are pre-generated and ready for Postman testing:

1. **`test_payload_2026-01-04-163358-Functional Strength Training-Robert's Apple Watch Ultra 3.json`**
   - Strength training workout from Apple Watch
   - Small file (11 KB) - good for quick tests
   - Tests: HR tracking without power data

2. **`test_payload_2026-01-10-211457-Indoor Cycling-RunGap.json`**
   - Indoor cycling workout from RunGap
   - Medium file (52 KB)
   - Tests: Power, cadence, HR zones, basic cycling metrics

3. **`test_payload_2026-01-12-183000-Indoor Cycling-RunGap.json`**
   - Indoor cycling workout from RunGap
   - Large file (121 KB)
   - Tests: Full metrics including TSS, IF, NP, aerobic efficiency

## Converting Additional Files

To convert any FIT file to a JSON payload:

```bash
python3 << 'EOF'
import base64
import json
from pathlib import Path

# Change this to your target FIT file
fit_file = "2026-01-06-220813-Indoor Cycling-HealthFit.fit"

with open(fit_file, 'rb') as f:
    content = f.read()
    b64_content = base64.b64encode(content).decode('utf-8')

payload = {
    "athlete_id": "rob",
    "source_item_id": f"test_{fit_file.replace('.fit', '')}",
    "source_file_name": fit_file,
    "source_file_path": f"/Apps/HealthFit/{fit_file}",
    "source_drive_id": "b!test-drive-id",
    "source_etag": f'"{hash(fit_file) & 0xFFFFFFFF:08x}"',
    "file_size_bytes": len(content),
    "file_content_b64": b64_content
}

output_name = f"test_payload_{fit_file.replace('.fit', '.json')}"
with open(output_name, 'w') as out:
    json.dump(payload, out, indent=2)

print(f"Created {output_name}")
EOF
```

## Usage in Tests

### Postman

Import the collection from `../postman_collection.json` and use the "Real Data Tests" folder.

### curl

```bash
curl -X POST http://localhost:7071/api/process_fit \
  -H "Content-Type: application/json" \
  -d @test_payload_2026-01-12-183000-Indoor\ Cycling-RunGap.json
```

### Python

```python
import requests
import json

with open('test_payload_2026-01-12-183000-Indoor Cycling-RunGap.json') as f:
    payload = json.load(f)

response = requests.post(
    'http://localhost:7071/api/process_fit',
    json=payload
)
print(response.json())
```

## What Gets Tested

- **Strength Training**: HR metrics without power data, different sport type
- **Cycling (Short)**: Power zones, cadence, speed, distance, basic calculations
- **Cycling (Long)**: TSS, Normalized Power, Intensity Factor, aerobic efficiency, HR drift, decoupling
- **Various Sources**: Apple Watch, HealthFit, RunGap - tests different FIT file formats
- **File Sizes**: From 11 KB to 121 KB - tests parsing performance

## Expected Metrics by File

### Strength Training (Jan 4)

- Heart rate zones and averages
- Duration and calories
- No power/distance data

### Indoor Cycling (Jan 10 - Short)

- Power metrics (avg, max, normalized)
- HR zones and time-in-zone
- Cadence and speed
- Basic TSS calculation

### Indoor Cycling (Jan 12 - Long)

- Full power analysis with FTP
- TSS, Intensity Factor, Variability Index
- Aerobic Efficiency (EF)
- HR drift and aerobic decoupling
- Time in all zones (HR and Power)

## File Integrity

All FIT files are real workouts exported from actual devices. The base64 encoding preserves binary integrity.
