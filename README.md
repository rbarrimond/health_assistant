# Health Assistant - FIT File Processor

Azure Function for parsing HealthFit FIT files from OneDrive and storing
metrics in Azure Table Storage according to the workout schema.

See [WORKOUT_SCHEMA.md](./WORKOUT_SCHEMA.md) for complete data specification and [WORKOUT_INTELLIGENCE_AGENT_VISION.md](./WORKOUT_INTELLIGENCE_AGENT_VISION.md) for system design principles.

## Architecture

- **Trigger**: HTTP endpoint called by Power Automate monitoring OneDrive
- **Input**: Base64-encoded FIT file + metadata in JSON payload
- **Processing**: FIT parsing -> metric extraction -> zone computation
- **Output**: Azure Tables (Workouts, WeeklyRollups, IngestionState)

## Configuration

Environment variables required:

- AzureWebJobsStorage: Connection string to Azure Storage account
- Or AZURE_STORAGE_ACCOUNT_URL: Direct storage account URL (with DefaultAzureCredential)

Optional:

- DEFAULT_ATHLETE_ID: Default athlete identifier (default: 'rob')
- DEFAULT_FTP: Default FTP for power zones (default: 250W)
- DEFAULT_MAX_HR: Default max HR for heart rate zones (default: 190bpm)
- HR_ZONE_BASIS: Heart rate zone calculation method - 'HRmax', 'LTHR' (Lactate Threshold), or 'HRR' (Heart Rate Reserve/Karvonen) (default: 'HRmax')
- HR_ZONE_REFERENCE_BPM: Reference HR for zone calculation (0 = auto-detect from workout) (default: 0)
- HR_RESTING_BPM: Resting heart rate for HRR method (default: 60bpm)
- ONEDRIVE_FOLDER_PATH: OneDrive path being monitored (default: '/Apps/HealthFit')

## Local Development

1. Set up Python environment:

   ```bash
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create local.settings.json with storage account details:

   ```json
   {
     "IsEncrypted": false,
     "Values": {
       "AzureWebJobsStorage": "DefaultEndpointsProtocol=https;AccountName=xxx;AccountKey=xxx;EndpointSuffix=core.windows.net",
       "FUNCTIONS_WORKER_RUNTIME": "python"
     }
   }
   ```

3. Run locally:

   ```bash
   func start
   ```

4. Test the function:

   ```bash
   curl -X POST http://localhost:7071/api/process_fit \\
     -H "Content-Type: application/json" \\
     -d @test_payload.json
   ```

## Deployment

Deploy to Azure:

```bash
func azure functionapp publish <FUNCTION_APP_NAME>
```

## Integration with Power Automate

Create a Power Automate flow that:

1. Monitors /Apps/HealthFit folder in OneDrive
2. For each new .fit file:
   - Read file content
   - Convert to base64
   - Extract metadata (itemId, name, path, size)
   - POST to /api/process_fit endpoint with function key auth
