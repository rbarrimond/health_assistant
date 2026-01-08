# Azure Functions Deployment Guide

Complete instructions for deploying the Health Assistant FIT file processor to Azure.

## Prerequisites

- Azure subscription with active credits
- Azure Functions (Python 3.12 runtime)
- Azure Storage Account (Table Storage + Blob optional)
- Azure CLI installed locally
- Function Core Tools installed
- Power Automate subscription (for OneDrive monitoring)

## Step 1: Prepare Azure Resources

### Create Storage Account

```bash
# Set variables
RESOURCE_GROUP="health-assistant-rg"
LOCATION="eastus"
STORAGE_ACCOUNT="healthfit$(date +%s)"
FUNCTION_APP="fitprocessor-$(date +%s)"

# Create resource group
az group create --name $RESOURCE_GROUP --location $LOCATION

# Create storage account
az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku Standard_LRS
```

### Create Function App

```bash
# Create Function App (Python 3.12)
az functionapp create \
  --resource-group $RESOURCE_GROUP \
  --consumption-plan-location $LOCATION \
  --runtime python \
  --runtime-version 3.12 \
  --functions-version 4 \
  --name $FUNCTION_APP \
  --storage-account $STORAGE_ACCOUNT \
  --os-type Linux

# Enable authentication (optional but recommended)
az functionapp identity assign --resource-group $RESOURCE_GROUP --name $FUNCTION_APP
```

### Create Table Storage Tables

```bash
# Get storage key
STORAGE_KEY=$(az storage account keys list \
  --resource-group $RESOURCE_GROUP \
  --account-name $STORAGE_ACCOUNT \
  --query '[0].value' -o tsv)

# Create tables
for TABLE in Workouts WeeklyRollups IngestionState; do
  az storage table create \
    --account-name $STORAGE_ACCOUNT \
    --account-key $STORAGE_KEY \
    --name $TABLE
done
```

## Step 2: Configure Function App Settings

```bash
# Get connection string
CONN_STRING=$(az storage account show-connection-string \
  --resource-group $RESOURCE_GROUP \
  --name $STORAGE_ACCOUNT \
  --query connectionString -o tsv)

# Set app settings
az functionapp config appsettings set \
  --name $FUNCTION_APP \
  --resource-group $RESOURCE_GROUP \
  --settings \
    "AzureWebJobsStorage=$CONN_STRING" \
    "FUNCTIONS_WORKER_RUNTIME=python" \
    "DEFAULT_ATHLETE_ID=rob" \
    "DEFAULT_FTP=250" \
    "DEFAULT_MAX_HR=190" \
    "ONEDRIVE_FOLDER_PATH=/Apps/HealthFit"
```

## Step 3: Deploy Function Code

### Using Azure Functions Core Tools (Local)

```bash
# Login to Azure
az login

# Deploy from local directory
func azure functionapp publish $FUNCTION_APP --python

# View deployment logs
az functionapp deployment source show \
  --name $FUNCTION_APP \
  --resource-group $RESOURCE_GROUP
```

### Using GitHub Actions (CI/CD)

See `.github/workflows/deploy.yml` for automated deployment on push to main.

## Step 4: Get Function URL and Key

```bash
# Get function URL
FUNCTION_URL=$(az functionapp function show \
  --resource-group $RESOURCE_GROUP \
  --name $FUNCTION_APP \
  --function-name ProcessFitFiles \
  --query '{url:invokeUrlTemplate}' -o tsv)

# Get function key
FUNCTION_KEY=$(az functionapp keys list \
  --resource-group $RESOURCE_GROUP \
  --name $FUNCTION_APP \
  --query 'functionKeys.default' -o tsv)

echo "Function URL: $FUNCTION_URL?code=$FUNCTION_KEY"
```

## Step 5: Configure Power Automate Flow

See [POWER_AUTOMATE_SETUP.md](./POWER_AUTOMATE_SETUP.md) for detailed instructions.

### Quick Setup

1. Create automated flow → "When a file is created"
2. Trigger on OneDrive folder: `/Apps/HealthFit/`
3. Add HTTP action to call Function URL with payload

## Step 6: Monitor and Test

### View Function Logs

```bash
# Stream logs in real-time
func azure functionapp logstream $FUNCTION_APP

# Or use Azure CLI
az webapp log tail --name $FUNCTION_APP --resource-group $RESOURCE_GROUP
```

### Check Application Insights

```bash
# Enable Application Insights
az functionapp app-insights-enable \
  --name $FUNCTION_APP \
  --resource-group $RESOURCE_GROUP
```

### Manual Test

```bash
# Upload test FIT file to OneDrive /Apps/HealthFit/
# Or manually call the function:

curl -X POST "https://$FUNCTION_APP.azurewebsites.net/api/process_fit?code=$FUNCTION_KEY" \
  -H "Content-Type: application/json" \
  -d @test_payload_example.json
```

### Verify Data in Table Storage

```bash
# View stored workouts
az storage table entity query \
  --account-name $STORAGE_ACCOUNT \
  --account-key $STORAGE_KEY \
  --table-name Workouts

# Check ingestion state
az storage table entity query \
  --account-name $STORAGE_ACCOUNT \
  --account-key $STORAGE_KEY \
  --table-name IngestionState
```

## Troubleshooting

### Function Not Triggering

- Verify Power Automate flow is enabled
- Check Application Insights logs for errors
- Ensure OneDrive folder path is correct (`/Apps/HealthFit/`)

### "File already processed" on new files

- Check IngestionState table for existing entries
- Clear state if needed: `az storage table delete --name IngestionState`

### Storage Connection Issues

- Verify connection string in function app settings
- Check firewall rules if using Virtual Networks
- Ensure storage account key hasn't been rotated

### FIT Parsing Errors

- Verify FIT file is valid (use `fitparse` CLI)
- Check log for specific parsing error
- May need to support different FIT file versions

## Scaling and Performance

### For High Volume

```bash
# Switch to Premium plan for better performance
az functionapp plan create \
  --name $FUNCTION_APP-plan \
  --resource-group $RESOURCE_GROUP \
  --sku EP1 \
  --is-linux

# Increase function timeout if needed
# Edit function_app/function_app.json:
# "functionTimeout": "00:30:00"
```

### Cost Optimization

- Use Consumption plan for occasional uploads
- Set up alerts for exceeding budget
- Archive old ingestion state data to blob storage

## Cleanup

```bash
# Delete all resources when done
az group delete --name $RESOURCE_GROUP --yes
```

## Advanced: Using Microsoft Graph for Monitoring

Instead of Power Automate, monitor OneDrive directly:

```bash
# Install Graph SDK
pip install msgraph-sdk

# Create timer-triggered function to check OneDrive changes
# See FitParser/graph_monitor.py for implementation
```

## CI/CD with GitHub Actions

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Azure Functions

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: azure/functions-action@v1
        with:
          app-name: ${{ secrets.FUNCTION_APP_NAME }}
          package: '.'
          publish-profile: ${{ secrets.AZURE_FUNCTIONAPP_PUBLISH_PROFILE }}
```

Get publish profile:
```bash
az functionapp deployment list-publishing-profiles \
  --name $FUNCTION_APP \
  --resource-group $RESOURCE_GROUP \
  --xml > publish-profile.xml
```

Then add as GitHub secret: `AZURE_FUNCTIONAPP_PUBLISH_PROFILE`
