# Configuration Files

## physiometrics.json

The `physiometrics.json` file contains current athlete-specific configuration for heart rate and power metrics. This represents your *current physiological truth* and is snapshotted into each workout record during ingestion.

### Example Structure

See `physiometrics.json.example` for a complete example.

### Heart Rate Configuration

- **basis**: Zone calculation method
  - `HRmax` - Percentage of maximum heart rate (default)
  - `LTHR` - Lactate Threshold Heart Rate method
  - `HRR` - Heart Rate Reserve (Karvonen) method
- **lthr_bpm**: Lactate Threshold Heart Rate value (used with LTHR basis)
- **hr_max_bpm**: Maximum Heart Rate value (used with HRmax or HRR basis)
- **resting_hr_bpm**: Resting Heart Rate (used with HRR basis; default 60)
- **zones**: Zone definitions with percentage boundaries (relative to reference value)

### Power Configuration

- **ftp_watts**: Functional Threshold Power in watts
- **zones**: Zone definitions with percentage boundaries (relative to FTP)

## Configuration Precedence

The Config system loads values in this order:

1. **Environment Variables** (highest priority - deployment overrides)
   - `HR_ZONE_BASIS` - Heart rate zone basis
   - `HR_ZONE_REFERENCE_BPM` - HR max or LTHR value
   - `HR_RESTING_BPM` - Resting heart rate
   - `DEFAULT_FTP` - Functional Threshold Power
   - `PHYSIOMETRICS_PATH` - Path to custom physiometrics.json

2. **physiometrics.json** (recommended - athlete profile)
   - Load from `config/physiometrics.json`
   - Or override location with `PHYSIOMETRICS_PATH` env var

3. **Hard Defaults** (lowest priority - fallback values)
   - HR basis: `HRmax`
   - Resting HR: `60 bpm`
   - FTP: `250 watts`

## Setup

1. Copy `physiometrics.json.example` to `physiometrics.json`:

   ```bash
   cp config/physiometrics.json.example config/physiometrics.json
   ```

2. Edit `config/physiometrics.json` with your athlete metrics

3. The Config class will automatically load it at runtime
