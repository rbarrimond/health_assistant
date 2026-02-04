# Testing

> **Source of Truth**: See [WORKOUT_SCHEMA.md](../WORKOUT_SCHEMA.md) for the complete specification of expected fields and metrics. This document describes the test coverage of that schema.

## Test Summary

**Status:** ✅ All 158 tests passing

- **FitParser Module:** 67 unit tests
- **Configuration Module:** 24 tests
- **HTTP Endpoints:** 20 tests
- **Semantic Layer:** 28 tests
- **Physiometrics & Withings:** 18 tests
- **Table Storage:** 11 tests
- **Smoke Tests:** 6 tests
- **Schema Validation:** 5 tests
- **Test Execution Time:** ~1.3s
- **Code Coverage:** High coverage across core modules

## Test Organization

### Configuration Tests (test_config.py)

**1. TestHeartRateConfigDataclass** (2 tests)

Tests for heart rate configuration data structure

- Heart rate config creation with valid parameters
- Config immutability (frozen dataclass)

**2. TestPowerConfigDataclass** (2 tests)

Tests for power configuration data structure

- Power config creation with valid parameters
- Config immutability (frozen dataclass)

**3. TestConfigPhysiometricsFile** (2 tests)

Tests for physiometrics file path resolution

- Default file location (~/.config/health_assistant/physiometrics.json)
- Path expansion with tilde (~)

**4. TestConfigLoadPhysiometrics** (4 tests)

Tests for loading physiometrics configuration from file

- Load from JSON file successfully
- Caching loaded configuration
- Force reload to bypass cache
- Handle missing file gracefully

**5. TestConfigHrConfig** (5 tests)

Tests for heart rate configuration retrieval

- Default configuration values
- Environment variable override for zone basis (HRmax, LTHR, HRR)
- Environment variable override for resting HR
- Loading from physiometrics file
- Default zone definitions

**6. TestConfigPowerConfig** (4 tests)

Tests for power configuration retrieval

- Default configuration values
- Environment variable override for FTP
- Loading from physiometrics file
- Default zone definitions

**7. TestConfigSavePhysiometrics** (3 tests)

Tests for saving physiometrics configuration

- Save requires table storage instance
- Saving clears configuration cache
- Returns timestamp of saved configuration

**8. TestConfigHistory** (2 tests)

Tests for physiometrics history retrieval

- Returns empty list when no storage configured
- Delegates to storage layer when available

### FitParser Tests (test_fit_parser.py)

**9. TestComputeFileHash** (3 tests)

Tests for the `compute_file_hash()` utility function

- Hash format validation (64-char SHA256 hex)
- Hash consistency for same file
- Different hashes for different files

**10. TestFitParserInitialization** (2 tests)

Tests for FitParser object creation and initial state

- File path storage
- Empty state initialization

**11. TestFitParserCaching** (3 tests)

Tests for message caching optimization

- File ID message caching
- Session message caching
- Record message lazy loading and caching

**12. TestFitParserFieldExtraction** (3 tests)

Tests for low-level field extraction utility

- Value extraction from FIT messages
- None message handling
- Missing field handling

**13. TestFitParserSportExtraction** (3 tests)

Tests for sport/activity type extraction

- Sport enum name extraction (with lowercasing)
- Sub-sport extraction
- Handling missing file_id message

**14. TestFitParserTimeExtraction** (3 tests)

Tests for time-related metrics

- Start time in ISO format UTC
- Duration in seconds
- Handling missing session data

**15. TestFitParserDistanceExtraction** (2 tests)

Tests for distance and elevation metrics

- Total distance in meters (float)
- Elevation gain in meters

**16. TestFitParserSpeedExtraction** (2 tests)

Tests for speed metrics

- Average speed in m/s
- Maximum speed in m/s

**17. TestFitParserHeartRateExtraction** (2 tests)

Tests for HR metrics computed from record data

- Average HR from record messages
- Max HR from record messages

**18. TestFitParserRecordDataExtraction** (2 tests)

Tests for extracting arrays from FIT record messages

- Extracting all values for a field
- Handling missing fields in records

**19. TestFitParserZoneComputation** (7 tests)

Tests for HR zone and power zone calculations

- Zone definitions for HRmax method (5-zone)
- Zone definitions for LTHR method (based on % of threshold)
- Zone definitions for HRR/Karvonen method
- Reference BPM resolution (provided, derived, with factors)
- Zone computation with missing data

**20. TestFitParserFullParse** (5 tests)

Integration tests for complete parse workflow

- Parse returns dictionary
- All required keys present in output
- Sport extraction in full parse
- HR zone computation when data available
- File not found error handling

**21. TestFitParserEdgeCases** (3 tests)

Tests for edge cases and boundary conditions

- Missing manufacturer field handling
- Zero values handled correctly (not treated as None)
- Filtering None values from record data

**22. TestAdapterIntegration** (1 test)

Tests for pydantic entity adapter

- Mapping fitparse messages to Workout entities

**23. TestFitParserWithEntities** (1 test)

Tests for entity-based parsing workflow

- Using pydantic entities in parse output

### HTTP Function Endpoint Tests (test_function_endpoints.py)

**24. TestHealthCheckEndpoint** (2 tests)

Tests for `/api/health` endpoint

- Returns 200 status code
- Returns JSON response

**25. TestReloadConfigEndpoint** (3 tests)

Tests for `/api/config/reload` endpoint

- Successfully reloads configuration from file
- Handles file not found errors
- Handles JSON parsing errors

**26. TestUpdateConfigEndpoint** (4 tests)

Tests for `/api/config/update` endpoint (POST)

- Successfully updates and persists configuration
- Validates JSON payload format
- Ensures payload is a dictionary
- Handles storage errors gracefully

**27. TestConfigHistoryEndpoint** (5 tests)

Tests for `/api/config/history` endpoint

- Returns configuration history successfully
- Respects limit parameter
- Caps limit at maximum value (100)
- Validates limit parameter type
- Handles query errors

### Physiometrics & Withings Tests (test_physiometrics_timeseries.py)

**28. TestPhysiometricsTimeSeries** (6 tests)

Tests for physiometrics time-series data management

- Store physiometrics with body composition data
- Update single metric value
- Retrieve physiometrics history
- Get physiometrics as of specific date
- Withings OAuth token storage and retrieval
- Webhook deduplication for duplicate notifications

**29. TestSemanticLayerPhysiometrics** (3 tests)

Tests for physiometrics semantic layer queries

- Get current physiometrics values
- Update single physiometric value
- Get physiometrics trends over time

**30. TestWithingsClient** (2 tests)

Tests for Withings API client integration

- Parse measurement group from webhook payload
- Handle measurement group without weight data

### Schema Field Tests (test_schema_fields.py)

**31. TestSchemaFieldImplementation** (5 tests)

Tests for WORKOUT_SCHEMA.md field implementation

- Power zone boundaries computed (14 boundary fields)
- Training load metrics computed (TSS and IF)
- Aerobic efficiency metrics computed (EF, drift, decoupling)
- Resting HR extraction from workout data
- Short workout skips aerobic efficiency (30min threshold)

### Semantic Layer Tests (test_semantic_layer.py)

**32. TestPlanningContext** (4 tests)

Tests for planning context aggregation

- Get basic planning context with workout summary
- Detect last hard training day
- Detect last long training day
- Calculate cumulative training minutes

**33. TestWorkoutQueries** (3 tests)

Tests for workout querying with filters

- List workouts with basic filters
- Query workouts by date range
- Filter workouts by sport type

**34. TestWeeklyRollupQueries** (2 tests)

Tests for weekly aggregation queries

- Get weekly rollup data
- Calculate weekly totals and averages

**35. TestZoneDistribution** (2 tests)

Tests for training zone distribution analysis

- Calculate time in each heart rate zone
- Calculate time in each power zone

**36. TestAnalysisQueries** (2 tests)

Tests for training analysis queries

- Aerobic decoupling trends
- Efficiency trends summary

**37. TestHelperMethods** (15 tests)

Tests for semantic layer utility functions

- Get month partitions for single month
- Get month partitions spanning multiple months
- Find last hard training day
- Find last long training day (not found scenario)
- Sum zone time across workouts
- Sum high-intensity training time
- Detect notable flags: missing HR data
- Detect notable flags: high aerobic decoupling
- Detect notable flags: very short workout
- Convert workout entity to dictionary
- Convert workout entity with record data to dictionary
- Additional helper method tests (5 more)

### Semantic Layer Endpoint Tests (test_semantic_layer_endpoints.py)

**38. TestPlanningContextEndpoint** (3 tests)

Tests for `/api/planning/context` endpoint

- Validates athlete_id parameter is required
- Returns planning context successfully
- Caps days parameter at maximum

**39. TestListWorkoutsEndpoint** (3 tests)

Tests for `/api/workouts` endpoint

- Validates athlete_id parameter is required
- Returns workout list successfully
- Filters workouts by query parameters

**40. TestGetWorkoutEndpoint** (3 tests)

Tests for `/api/workouts/{workout_id}` endpoint

- Validates athlete_id parameter is required
- Returns workout details when found
- Returns 404 when workout not found

**41. TestWeeklyRollupsEndpoint** (3 tests)

Tests for `/api/rollups/weekly` endpoint

- Validates athlete_id parameter is required
- Returns weekly rollup data successfully
- Caps weeks parameter at maximum

**42. TestZoneDistributionEndpoint** (2 tests)

Tests for `/api/analysis/zones` endpoint

- Validates athlete_id parameter is required
- Returns zone distribution data successfully

**43. TestEfficiencyTrendsEndpoint** (3 tests)

Tests for `/api/analysis/efficiency` endpoint

- Validates athlete_id parameter is required
- Returns efficiency trend data successfully
- Caps days parameter at maximum

### Smoke Tests (test_smoke.py)

**44. Core Import & Integration Tests** (6 tests)

Basic smoke tests for core functionality

- FitParser module imports successfully
- Table storage module imports successfully
- Function app module is importable
- File hash computation works
- Payload structure validation
- Parse ingestion payload happy path

### Table Storage Tests (test_table_storage_physiometrics.py)

**45. TestStorePhysiometrics** (4 tests)

Tests for storing physiometrics data in Azure Table Storage

- Store physiometrics successfully
- Stores full JSON payload in entity
- Handles null/missing values gracefully
- Handles storage errors appropriately

**46. TestGetPhysiometrics** (4 tests)

Tests for retrieving physiometrics data

- Get latest physiometrics entry
- Fallback to individual fields if JSON missing
- Returns None when no data found
- Handles query errors

**47. TestListPhysiometricsHistory** (3 tests)

Tests for listing physiometrics history

- List history entries successfully
- Respects limit parameter
- Handles query errors

**48. TestEnsurePhysiometricsTable** (1 test)

Tests for table initialization

- Ensures PhysiometricsTimeSeries table is created

## Test Fixtures

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
- `mock_table_storage`: Azure Table Storage client mock
- `mock_semantic_layer`: Semantic layer instance for endpoint testing

## Running Tests

**Run all tests:**

```bash
pytest tests/ -v
```

**Run specific test file:**

```bash
pytest tests/test_fit_parser.py -v
pytest tests/test_schema_fields.py -v
pytest tests/test_semantic_layer.py -v
pytest tests/test_function_endpoints.py -v
```

**Run specific test class:**

```bash
pytest tests/test_fit_parser.py::TestComputeFileHash -v
```

**Run with coverage:**

```bash
pytest tests/ --cov=FitParser --cov-report=html
```

## Key Testing Patterns Used

1. **Mocking:** `unittest.mock.Mock` and `MagicMock` for FIT file simulation, Azure Table Storage, and HTTP requests
2. **Fixtures:** Pytest fixtures for setup/teardown and data sharing across test modules
3. **Class-Based Organization:** Test classes group related functionality (e.g., endpoint validation, data extraction)
4. **Edge Cases:** Zero values, None handling, missing data, malformed inputs
5. **Integration:** Full parse workflow validation and end-to-end API testing
6. **Type Checking:** Verifying return types match annotations
7. **Error Handling:** Explicit tests for error conditions and exception paths
8. **Boundary Testing:** Parameter limits, capping, and validation

## Test Coverage Highlights

- **Configuration:** Complete coverage of file-based and environment-based config
- **HTTP Endpoints:** All 14 API endpoints tested with success and error cases
- **Semantic Layer:** Planning context, queries, aggregations, and helper methods
- **FIT Parsing:** Comprehensive unit tests for all extraction methods
- **Physiometrics:** Time-series storage, retrieval, and Withings integration
- **Table Storage:** CRUD operations and error handling

## Test Data

Real FIT workout files are available in [tests/data/](./data/README.md):

- Functional strength training sessions
- Indoor cycling workouts
- Outdoor walking activities
- Multiple formats (Apple Watch, HealthFit, RunGap exports)

## Dependencies

- pytest >= 8.3.0
- pytest-cov >= 5.0.0
- fitparse (mocked in most tests)
- azure-data-tables (mocked for table storage tests)
- Standard library: unittest.mock, datetime, pathlib, json

## Related Documentation

- [POSTMAN_GUIDE.md](./POSTMAN_GUIDE.md) - API testing with Postman
- [data/README.md](./data/README.md) - Test data files and payloads
- [WORKOUT_SCHEMA.md](../WORKOUT_SCHEMA.md) - Data schema being tested
- [SEMANTIC_LAYER_API.md](../SEMANTIC_LAYER_API.md) - API endpoints being tested
