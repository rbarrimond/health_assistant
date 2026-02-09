# Test Data Files

This directory contains **real FIT workout files** and **pre-generated JSON payloads** for testing the Health Assistant Function App. These files are essential for integration testing and API validation.

## Why Real FIT Files?

Using actual workout files ensures:

- ✅ **Real-world parsing accuracy** - Tests handle actual device output, not synthetic data
- ✅ **Edge case discovery** - Real files expose parser issues that mock data wouldn't
- ✅ **Integration validation** - End-to-end testing with genuine FIT file structures
- ✅ **Regression prevention** - Changes don't break parsing of real workout types

## Available Files

### Real FIT Files (8 files)

| Filename | Date | Sport | Source | Features Tested |
| -------- | ---- | ----- | ------ | --------------- |
| `2026-01-04-163358-Functional Strength Training-Robert's Apple Watch Ultra 3.fit` | Jan 4 | Strength | Apple Watch | Heart rate tracking without power, strength training metrics |
| `2026-01-06-220813-Indoor Cycling-HealthFit.fit` | Jan 6 | Cycling | HealthFit | Indoor detection, basic cycling metrics |
| `2026-01-07-142711-Outdoor Walking-Robert's Apple Watch Ultra 3.fit` | Jan 7 | Walking | Apple Watch | GPS tracking, outdoor activity, HR zones |
| `2026-01-07-192805-Functional Strength Training-Robert's Apple Watch Ultra 3.fit` | Jan 7 | Strength | Apple Watch | Multiple strength sessions, workout variation |
| `2026-01-08-224701-Indoor Cycling-HealthFit.fit` | Jan 8 | Cycling | HealthFit | Indoor workout consistency testing |
| `2026-01-10-203100-Functional Strength Training-Robert's Apple Watch Ultra 3.fit` | Jan 10 | Strength | Apple Watch | Additional strength training variation |
| `2026-01-10-211457-Indoor Cycling-RunGap.fit` | Jan 10 | Cycling | RunGap | Power + HR zones, medium file (52 KB), complete metrics |
| `2026-01-12-183000-Indoor Cycling-RunGap.fit` | Jan 12 | Cycling | RunGap | **Full metrics**: TSS, IF, NP, efficiency, large file (121 KB) |

**Test Coverage**:

- ✓ Multiple workout types (cycling, strength, walking)
- ✓ Different device sources (Apple Watch, HealthFit, RunGap)
- ✓ Indoor and outdoor activities
- ✓ With and without power data
- ✓ Various file sizes (11 KB - 121 KB)
- ✓ Different date ranges (Jan 4 - Jan 12, 2026)

## Pre-Generated JSON Payloads (3 files)

Three JSON payloads are pre-generated and ready for immediate testing with Postman or curl:

### 1. Strength Training - Apple Watch (Small)

**File**: `test_payload_2026-01-04-163358-Functional Strength Training-Robert's Apple Watch Ultra 3.json`

- **Size**: ~15 KB (base64-encoded FIT file: 11 KB)
- **Sport**: Functional strength training
- **Device**: Apple Watch Ultra 3
- **Test Focus**:
  - Heart rate tracking without power data
  - Strength training workout type detection
  - HR zone calculation
  - Short/quick workout processing
- **Use Case**: Quick smoke tests, basic HR functionality

### 2. Indoor Cycling - RunGap (Medium)

**File**: `test_payload_2026-01-10-211457-Indoor Cycling-RunGap.json`

- **Size**: ~70 KB (base64-encoded FIT file: 52 KB)
- **Sport**: Indoor cycling
- **Device**: RunGap export
- **Test Focus**:
  - Power + HR metrics combined
  - Power zone calculation (7 zones)
  - HR zone calculation (5 zones)
  - Cadence tracking
  - Indoor activity detection
  - Medium file size handling
- **Use Case**: Standard workout ingestion testing

### 3. Indoor Cycling - RunGap (Large, Complete)

**File**: `test_payload_2026-01-12-183000-Indoor Cycling-RunGap.json`

- **Size**: ~162 KB (base64-encoded FIT file: 121 KB)
- **Sport**: Indoor cycling
- **Device**: RunGap export
- **Test Focus**:
  - **Complete metrics suite**: TSS, Intensity Factor, Normalized Power
  - **Aerobic efficiency**: EF (first/second half), HR drift, decoupling
  - Full power analysis (avg, max, NP, VI)
  - Comprehensive HR analysis
  - Large file parsing performance
  - All 100+ fields populated
- **Use Case**: Full integration tests, performance testing, complete metrics validation

## Payload Structure

Each JSON payload follows this structure:

```json
{
  "athlete_id": "rob",
  "source_item_id": "test_<filename_without_extension>",
  "source_file_name": "<original_fit_filename>",
  "source_file_path": "/Apps/HealthFit/<fit_filename>",
  "source_drive_id": "b!test-drive-id",
  "source_etag": "\"<hash>\"",
  "file_size_bytes": 121000,
  "file_content_b64": "<base64_encoded_fit_file>"
}
```

**Fields**:

- `athlete_id`: Identifies the athlete (defaults to "rob")
- `source_item_id`: Unique identifier for deduplication
- `source_file_name`: Original FIT filename
- `source_file_path`: OneDrive path (simulated)
- `source_drive_id`: OneDrive drive ID (simulated)
- `source_etag`: File version tag for idempotency
- `file_size_bytes`: Original FIT file size
- `file_content_b64`: Base64-encoded FIT file content

## Converting Additional FIT Files to JSON Payloads

Need to create a test payload from a new FIT file? Use this Python script:

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
print(f"File size: {len(content)} bytes")
print(f"JSON payload size: {len(json.dumps(payload))} bytes")
EOF
```

**Batch conversion** (all FIT files in directory):

```bash
python3 << 'EOF'
import base64
import json
from pathlib import Path

for fit_path in Path('.').glob('*.fit'):
    fit_file = fit_path.name
    
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

    print(f"✓ Created {output_name} ({len(content)} bytes FIT → {len(json.dumps(payload))} bytes JSON)")
EOF
```

## File Naming Convention

**FIT files**: `YYYY-MM-DD-HHMMSS-<Activity Type>-<Device>.fit`

Example: `2026-01-12-183000-Indoor Cycling-RunGap.fit`

**JSON payloads**: `test_payload_<same-as-fit-file>.json`

Example: `test_payload_2026-01-12-183000-Indoor Cycling-RunGap.json`

**Why this convention?**:

- ✓ Chronological sorting by date
- ✓ Easy workout identification
- ✓ Device source tracking
- ✓ Automatic date parsing for OneDrive sync lookback

## Testing Best Practices

### When to Use Which File

**Quick smoke tests**:

- Use: Strength training payload (11 KB)
- Purpose: Fast ingestion validation, basic functionality

**Standard integration tests**:

- Use: Medium cycling payload (52 KB)
- Purpose: Normal workout processing, zone calculation

**Full metrics validation**:

- Use: Large cycling payload (121 KB)
- Purpose: Complete feature set, performance testing

**Multi-sport testing**:

- Use: All available FIT files
- Purpose: Ensure parser handles different workout types

### Adding New Test Files

**When to add a new file**:

- New sport type not yet covered
- Different device/export format
- Edge case discovered in production
- Regression test for parsing bug

**Checklist for new files**:

1. ✅ File follows naming convention
2. ✅ Contains interesting metrics (not empty workout)
3. ✅ Generate JSON payload with script above
4. ✅ Add entry to table in this README
5. ✅ Test locally: `curl -X POST ... -d @test_payload_newfile.json`
6. ✅ Add to Postman collection if valuable for API testing
7. ✅ Commit both .fit and .json files

## File Size Guidelines

| Size Range  | Use Case                      | Example                              |
| ----------- | ----------------------------- | ------------------------------------ |
| < 20 KB     | Quick tests, smoke tests      | Strength training sessions           |
| 20-80 KB    | Standard integration tests    | Short-medium cycling workouts        |
| 80-150 KB   | Complete metrics tests        | Full cycling workouts with power     |
| > 150 KB    | Performance testing           | Long rides, multi-hour activities    |

**Note**: Base64 encoding increases file size by ~33%, so account for this in JSON payloads.

## Data Privacy

**Important**: All test FIT files in this directory are:

- ✅ From controlled test accounts or anonymized
- ✅ Free of personally identifiable information
- ✅ Safe to commit to public repository
- ✅ Representative of real workout structure

**Do NOT commit**:

- ❌ FIT files with usernames/emails
- ❌ Files with GPS coordinates of private locations
- ❌ Data from third-party athletes without permission

## Troubleshooting

### JSON Payload Errors

**"Invalid base64 encoding"**:

- Check that FIT file was read in binary mode (`'rb'`)
- Verify no line breaks in base64 string
- Ensure proper encoding: `base64.b64encode(content).decode('utf-8')`

**"File size mismatch"**:

- Verify `file_size_bytes` matches actual FIT file size
- Check that entire file was read (use `content = f.read()`)

### FIT File Parsing Errors

**"Unable to parse FIT file"**:

- Verify FIT file is not corrupted
- Open in FIT file viewer (e.g., FitFileViewer.com) to validate
- Check fitparse library can read it: `fitparse.FitFile(filename)`

**"Missing required fields"**:

- Some FIT files lack certain metrics (e.g., power data from non-power devices)
- This is expected - parser handles missing fields gracefully

## Related Documentation

- [../postman/README.md](../postman/README.md) - Postman collection testing guide
- [../README.md](../README.md) - Complete test suite documentation
- [../../docs/WORKOUT_SCHEMA.md](../../docs/WORKOUT_SCHEMA.md) - Expected workout fields
- [../../README.md](../../README.md) - Main project documentation

---

**Status**: 8 FIT files + 3 pre-generated JSON payloads ready for testing

**Last Updated**: February 2026

## Usage Examples

### Postman Testing

1. **Import the collection**:
   - Open Postman
   - Import `../postman/postman_collection.json`
   - Navigate to "Real Data Tests" folder

2. **Run pre-configured requests**:
   - Each request automatically loads the corresponding payload
   - No manual copy/paste needed
   - See [../postman/README.md](../postman/README.md) for details

### curl Testing

**Quick test with small file**:

```bash
curl -X POST http://localhost:7071/api/process_fit \
  -H "Content-Type: application/json" \
  -d @test_payload_2026-01-04-163358-Functional\ Strength\ Training-Robert\'s\ Apple\ Watch\ Ultra\ 3.json
```

**Full metrics test with large file**:

```bash
curl -X POST http://localhost:7071/api/process_fit \
  -H "Content-Type: application/json" \
  -d @test_payload_2026-01-12-183000-Indoor\ Cycling-RunGap.json
```

**Test against Azure deployment**:

```bash
curl -X POST "https://<your-function-app>.azurewebsites.net/api/process_fit?code=<function_key>" \
  -H "Content-Type: application/json" \
  -d @test_payload_2026-01-12-183000-Indoor\ Cycling-RunGap.json
```

### Python Testing

**Integration test example**:

```python
import requests
import json

with open('test_payload_2026-01-12-183000-Indoor Cycling-RunGap.json') as f:
    payload = json.load(f)

response = requests.post(
    'http://localhost:7071/api/process_fit',
    json=payload,
    headers={'Content-Type': 'application/json'}
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
```

**In pytest**:

```python
def test_real_fit_file_ingestion():
    """Test ingestion with real FIT file payload."""
    with open('tests/data/test_payload_2026-01-12-183000-Indoor Cycling-RunGap.json') as f:
        payload = json.load(f)
    
    # Use the FIT upload handler
    result, status = handler.handle(payload)
    
    assert status == 200
    assert result['status'] == 'success'
    assert 'workout_id' in result
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
