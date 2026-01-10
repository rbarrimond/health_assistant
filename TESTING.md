# Testing

## Test Summary

**Status:** ✅ All 47 tests passing

- **FitParser Module:** 42 unit tests
- **Schema Validation:** 5 schema field tests
- **Test Execution Time:** ~1.4s
- **Code Coverage:** 91% (FitParser module)

### Test Organization

#### 1. **TestComputeFileHash** (3 tests)

Tests for the `compute_file_hash()` utility function

- Hash format validation (64-char SHA256 hex)
- Hash consistency for same file
- Different hashes for different files

#### 2. **TestFitParserInitialization** (2 tests)

Tests for FitParser object creation and initial state

- File path storage
- Empty state initialization

#### 3. **TestFitParserCaching** (3 tests)

Tests for message caching optimization

- File ID message caching
- Session message caching
- Record message lazy loading and caching

#### 4. **TestFitParserFieldExtraction** (3 tests)

Tests for low-level field extraction utility

- Value extraction from FIT messages
- None message handling
- Missing field handling

#### 5. **TestFitParserSportExtraction** (3 tests)

Tests for sport/activity type extraction

- Sport enum name extraction (with lowercasing)
- Sub-sport extraction
- Handling missing file_id message

#### 6. **TestFitParserTimeExtraction** (3 tests)

Tests for time-related metrics

- Start time in ISO format UTC
- Duration in seconds
- Handling missing session data

#### 7. **TestFitParserDistanceExtraction** (2 tests)

Tests for distance and elevation metrics

- Total distance in meters (float)
- Elevation gain in meters

#### 8. **TestFitParserSpeedExtraction** (2 tests)

Tests for speed metrics

- Average speed in m/s
- Maximum speed in m/s

#### 9. **TestFitParserHeartRateExtraction** (2 tests)

Tests for HR metrics computed from record data

- Average HR from record messages
- Max HR from record messages

#### 10. **TestFitParserRecordDataExtraction** (2 tests)

Tests for extracting arrays from FIT record messages

- Extracting all values for a field
- Handling missing fields in records

#### 11. **TestFitParserZoneComputation** (7 tests)

Tests for HR zone and power zone calculations

- Zone definitions for HRmax method (5-zone)
- Zone definitions for LTHR method (based on % of threshold)
- Zone definitions for HRR/Karvonen method
- Reference BPM resolution (provided, derived, with factors)
- Zone computation with missing data

#### 12. **TestFitParserFullParse** (5 tests)

Integration tests for complete parse workflow

- Parse returns dictionary
- All required keys present in output
- Sport extraction in full parse
- HR zone computation when data available
- File not found error handling

#### 13. **TestFitParserEdgeCases** (3 tests)

Tests for edge cases and boundary conditions

- Missing manufacturer field handling
- Zero values handled correctly (not treated as None)
- Filtering None values from record data

#### 14. **TestAdapterIntegration** (1 test)

Tests for pydantic entity adapter

- Mapping fitparse messages to Workout entities

#### 15. **TestFitParserWithEntities** (1 test)

Tests for entity-based parsing workflow

- Using pydantic entities in parse output

#### 16. **TestSchemaFieldImplementation** (5 tests)

Tests for WORKOUT_SCHEMA.md field implementation

- `test_power_zone_boundaries_computed` - Verifies 14 power zone boundary fields
- `test_training_load_metrics_computed` - Verifies TSS and IF calculation
- `test_aerobic_efficiency_metrics_computed` - Verifies EF, drift, decoupling
- `test_resting_hr_extraction` - Verifies resting HR extraction
- `test_short_workout_skips_aerobic_efficiency` - Verifies 30min threshold

### Test Fixtures

**conftest.py** provides reusable fixtures:

- `sample_fit_file`: Temporary FIT file for testing
- `mock_fit_message`: Generic mock FIT message
- `mock_fit_file_with_data`: Complete mock with file_id and session messages
  - Contains realistic metric values (cycling workout)
  - Includes enum objects with proper `.name` attributes
- `mock_fit_file_with_records`: Mock with 10 record messages
  - Heart rate data: 140-170 bpm
  - Power data: 200-300 watts
  - Cadence data: 82-95 rpm

### Running Tests

**Run all tests:**

```bash
pytest tests/ -v
```

**Run specific test file:**

```bash
pytest tests/test_fit_parser.py -v
pytest tests/test_schema_fields.py -v
```

**Run specific test class:**

```bash
pytest tests/test_fit_parser.py::TestComputeFileHash -v
```

**Run with coverage:**

```bash
pytest tests/ --cov=FitParser --cov-report=html
```

### Key Testing Patterns Used

1. **Mocking:** `unittest.mock.Mock` and `MagicMock` for FIT file simulation
2. **Fixtures:** Pytest fixtures for setup/teardown and data sharing
3. **Parametrization:** Test organization with class-based grouping
4. **Edge Cases:** Zero values, None handling, missing data
5. **Integration:** Full parse workflow validation
6. **Type Checking:** Verifying return types match annotations

### Coverage Gaps

The 9% of uncovered code includes:

- Some exception handling paths
- Config and logging modules (minimal test coverage)

### Dependencies

- pytest >= 8.3.0
- pytest-cov >= 5.0.0
- fitparse (mocked in tests)
- Standard library: unittest.mock, datetime, pathlib
