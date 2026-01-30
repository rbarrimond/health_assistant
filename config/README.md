# Configuration Files

This directory contains configuration templates for local development and (legacy) Power Automate integration.
Only example/template files are committed; generated or user-specific configs stay local.

## physiometrics.json

The `physiometrics.json` file contains current athlete-specific configuration for heart rate and power metrics. This represents your *current physiological truth* and is snapshotted into each workout record during ingestion.

### Example Structure

See `physiometrics.json.example` for a complete example.
Create your local file from the example and do not commit it.

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

## power_automate_flow.json (Legacy)

The `power_automate_flow.json` file is an importable Power Automate cloud flow definition for legacy OneDrive FIT file monitoring and ingestion.

### Flow Definition

See `power_automate_flow.json.example` for the complete flow definition.
Create the JSON and any import zip locally when needed; do not commit them.

### Flow Components

- **Trigger**: OneDrive "file created (properties only)" on `/Apps/HealthFit` folder
- **Actions**:
  1. Get file content from OneDrive
  2. Convert file content to base64
  3. POST to Azure Function `process_fit` endpoint with metadata and file payload

### Setup

1. Copy the example file:

   ```bash
   cp config/power_automate_flow.json.example config/power_automate_flow.json
   ```

2. Edit `config/power_automate_flow.json` and replace placeholders:
   - `<FUNCTION_APP>` → Your Azure Function App name
   - `<FUNCTION_KEY>` → Your function key (from Azure portal)
   - `<ONEDRIVE_CONNECTION_ID>` → Your OneDrive connection ID
   - `"athlete_id": "rob"` → Your athlete identifier

3. Import to Power Automate:
   - Create a zip file containing the JSON (locally, do not commit)
   - Go to Power Automate → Solutions → Import
   - Upload and rebind the OneDrive connection

See [POWER_AUTOMATE_SETUP.md](../POWER_AUTOMATE_SETUP.md) for current iCloud sync instructions and legacy notes.

## Configuration Precedence

The Config system loads values in this order of precedence:

1. **Azure Table Storage** (highest priority - production recommended)
   - Physiometrics table via table_storage module
   - Allows runtime updates without redeployment
   - Requires `AzureWebJobsStorage` or `AZURE_STORAGE_ACCOUNT_URL` configured

2. **Environment Variables** (deployment overrides)
   - `HR_ZONE_BASIS` - Heart rate zone basis (HRmax, LTHR, or HRR)
   - `HR_ZONE_REFERENCE_BPM` - HR max or LTHR value
   - `HR_RESTING_BPM` - Resting heart rate
   - `DEFAULT_FTP` - Functional Threshold Power
   - `PHYSIOMETRICS_PATH` - Path to custom physiometrics.json file

3. **physiometrics.json** (local development)
   - Filesystem-based configuration
   - Load from `config/physiometrics.json`
   - Or override location with `PHYSIOMETRICS_PATH` env var

4. **Hard Defaults** (lowest priority - fallback values)
   - HR basis: `HRmax`
   - Resting HR: `60 bpm`
   - FTP: `250 watts`

## Local Development Setup

### Physiometrics Configuration

1. Copy `physiometrics.json.example` to `physiometrics.json`:

   ```bash
   cp config/physiometrics.json.example config/physiometrics.json
   ```

2. Edit `config/physiometrics.json` with your athlete metrics

3. The Config class will automatically load it at runtime

### Power Automate Flow (Optional, Legacy)

If maintaining the legacy OneDrive integration:

1. Copy `power_automate_flow.json.example` to `power_automate_flow.json`:

   ```bash
   cp config/power_automate_flow.json.example config/power_automate_flow.json
   ```

2. Edit with your Azure Function details and athlete ID

3. Import to Power Automate (see [POWER_AUTOMATE_SETUP.md](../POWER_AUTOMATE_SETUP.md))
