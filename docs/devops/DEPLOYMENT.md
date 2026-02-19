# Azure Functions Deployment Guide

Version: 1.0.1

> **Source of Truth**: See [WORKOUT_SCHEMA.md](../gpt/WORKOUT_SCHEMA.md) and [WORKOUT_INTELLIGENCE_AGENT_VISION.md](../gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md) for system design. This document describes deployment procedures only.
>
> **For Monitoring & Analytics**: See [MONITORING.md](./MONITORING.md) for comprehensive monitoring strategy including Power BI dashboards and athlete guide.

Complete instructions for deploying the Health Assistant FIT file processor to Azure.

## Prerequisites

- Azure subscription with active credits
- Azure Functions (Python 3.13 runtime)
- Azure Storage Account (Table Storage + Blob optional)
- Azure CLI installed locally
- Function Core Tools installed
- OneDrive Personal account (for delegated OAuth sync)

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
# Create Function App (Python 3.13)
az functionapp create \
  --resource-group $RESOURCE_GROUP \
  --consumption-plan-location $LOCATION \
  --runtime python \
  --runtime-version 3.13 \
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
for TABLE in Workouts WeeklyRollups IngestionState Physiometrics OneDriveTokens WithingsTokens AgentPreferences AgentObservations; do
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
    "ONEDRIVE_CLIENT_ID=<your-app-client-id>" \
    "ONEDRIVE_CLIENT_SECRET=<your-app-client-secret>" \
    "ONEDRIVE_REDIRECT_URI=https://$FUNCTION_APP.azurewebsites.net/api/onedrive/callback" \
    "ONEDRIVE_SCOPES=Files.ReadWrite offline_access" \
    "ONEDRIVE_FOLDER_PATH=/Apps/HealthFit" \
    "ONEDRIVE_SYNC_LOOKBACK_DAYS=30"
```

## Step 3: Deploy Function Code

### Option A: Using VS Code (Recommended for Development)

1. Install the [Azure Functions extension](https://marketplace.visualstudio.com/items?itemName=ms-azuretools.vscode-azurefunctions) for VS Code

2. Sign in to Azure:
   - Click the Azure icon in the sidebar
   - Click "Sign in to Azure"

3. Deploy to Azure:
   - Click the Azure icon in the sidebar
   - Expand your subscription and Function Apps
   - Right-click your Function App → "Deploy to Function App"
   - Select the workspace folder containing `function_app.py`
   - Confirm the deployment

4. View logs:
   - Right-click your Function App → "Start Streaming Logs"

### Option B: Using Azure Functions Core Tools (Local Terminal)

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

### Option C: Using GitHub Actions (CI/CD)

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

## Step 5: Configure OneDrive (Personal) Sync

See [BACKENDS.md](./BACKENDS.md#healthfit-onedrive-integration) for detailed OAuth setup.

### Quick Setup

1. Register the OneDrive app and set redirect URI
2. Set ONEDRIVE_* app settings above
3. Authorize: `GET /api/onedrive/authorize?athlete_id=rob`
4. Run `POST /api/onedrive/sync` (defaults to async; set `async=false` to block) or wait for the hourly timer

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
curl -X POST "https://$FUNCTION_APP.azurewebsites.net/api/onedrive/sync?code=$FUNCTION_KEY" \
  -H "Content-Type: application/json" \
  -d '{"days": 30, "athlete_id": "rob", "async": true}'
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

- Verify OneDrive OAuth is completed (tokens stored)
- Check Application Insights logs for errors
- Ensure the OneDrive trigger folder path is correct (`/Apps/HealthFit`)

### "File already processed" on new files

- Check IngestionState table for existing entries
- Clear state if needed: `az storage table delete --name IngestionState`

### Storage Connection Issues

- Verify connection string in function app settings
- Check firewall rules if using Virtual Networks
- Ensure storage account key hasn't been rotated

### FIT Parsing Errors

- Verify FIT file is valid (use `fitdecode` CLI)
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

## Monitoring & Analytics

### Data Analytics with Power BI

For visualizing training trends, physiometrics, and workload management:

**See [MONITORING.md](./MONITORING.md)** for complete monitoring strategy including Power BI dashboard setup and athlete user guide.

**Quick setup:**

1. Get Power BI access ($0 free or $10/month Pro)
2. Connect to your Storage Account
3. Build dashboard from provided templates
4. Set auto-refresh (every 24 hours)

### Application Insights for Function Health

Monitor the Azure Function App itself (errors, latency, throughput):

```bash
# Create Application Insights
az monitor app-insights component create \
  --app fitprocessor-insights \
  --location $LOCATION \
  --resource-group $RESOURCE_GROUP

# Link to Function App
INSIGHTS_KEY=$(az monitor app-insights component show \
  --app fitprocessor-insights \
  --resource-group $RESOURCE_GROUP \
  --query instrumentationKey -o tsv)

az functionapp config appsettings set \
  --name $FUNCTION_APP \
  --resource-group $RESOURCE_GROUP \
  --settings "APPINSIGHTS_INSTRUMENTATION_KEY=$INSIGHTS_KEY"
```

### Set Up Alerts

```bash
# Alert when function errors exceed threshold
az monitor metrics alert create \
  --name "FitProcessor Function Errors" \
  --resource-group $RESOURCE_GROUP \
  --scopes "/subscriptions/$(az account show -q --query id -o tsv)/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$FUNCTION_APP" \
  --condition "avg Exceptions > 5" \
  --window-size 1h \
  --evaluation-frequency 15m \
  --action "log"
```

### View Diagnostics

```bash
# Stream live logs
az functionapp log tail \
  --name $FUNCTION_APP \
  --resource-group $RESOURCE_GROUP

# View in Azure Portal
# Function App → Monitoring → Logs
# or
# Application Insights resource → Performance, Failures
```

## CI/CD with GitHub Actions

The repository includes `.github/workflows/deploy.yml` for automated deployment.

### How the Workflow Works

**Key Concept**: The workflow is split into two phases - testing locally in CI, and building/deploying remotely on Azure.

#### Phase 1: Testing in GitHub Actions (CI Environment)

- **Python Setup**: Required here to run tests in the CI environment
- **Install Runtime Dependencies**: From `requirements.txt` (what the app needs to run)
- **Install Dev Dependencies**: From `pyproject.toml[dev]` (pytest, coverage tools, etc.)
- **Run Tests**: Executes `pytest` - if tests fail, deployment is blocked

#### Phase 2: Deployment to Azure (Azure Environment)

- **respect-funcignore**: Excludes unnecessary files (tests, cache, `.venv`, etc.) from upload
- **scm-do-build-during-deployment**: Azure runs its own build process on the server
- **enable-oryx-build**: Azure's Oryx auto-detects Python and installs from `requirements.txt`

**Important**: Azure does NOT use our CI environment's Python setup. It builds fresh on the server using Oryx. The Python setup in the workflow is ONLY for running tests before deployment.

### Setup GitHub Actions Deployment

**Current Method**: Using Publish Profile (simple but less secure)

#### Required Secret

Add this secret to your GitHub repository (Settings → Secrets and variables → Actions):

- `AZURE_FUNCTIONAPP_PUBLISH_PROFILE`: Download from Azure Portal
  1. Navigate to your Function App
  2. Click "Get publish profile" in the Overview
  3. Copy the entire XML content
  4. Paste as GitHub secret

#### Function App Name

The workflow targets: `func-healthassistant-prod-59o7`

If you deploy a new Function App via Terraform, update `AZURE_FUNCTIONAPP_NAME` in `.github/workflows/deploy.yml`.

### How It Works

The workflow:

1. **Triggers**: Automatically on push to `main`, or manually via workflow dispatch
2. **Testing Phase**: Sets up Python, installs dependencies, runs pytest
3. **Deployment Phase**: If tests pass, deploys to Azure Functions
4. **Azure Build**: Azure receives the code and runs Oryx build (detects Python, installs requirements)

### Troubleshooting Deployment

#### Tests Fail in CI

- Check test logs in GitHub Actions → Actions tab → Failed workflow
- Run tests locally: `pytest tests/ -v`
- Ensure all dev dependencies are listed in `pyproject.toml[dev]`

#### Deployment Succeeds but Function Doesn't Work

- **Check Azure Logs**: `az functionapp log tail --name func-healthassistant-prod-59o7 --resource-group <RG_NAME>`
- **Common Issue**: Missing environment variables in Azure
  - Verify settings: `az functionapp config appsettings list --name <APP_NAME> --resource-group <RG_NAME>`
- **Common Issue**: Wrong Python version on Azure
  - Should be 3.13 - check runtime: `az functionapp show --name <APP_NAME> --resource-group <RG_NAME> --query "siteConfig.linuxFxVersion"`

#### Deployment Fails During Upload

- **Check Publish Profile**: Ensure the secret `AZURE_FUNCTIONAPP_PUBLISH_PROFILE` is valid
  - Profiles expire if Function App is recreated
  - Re-download from Azure Portal if needed
- **Check Function App Exists**: Verify the Function App is running in Azure

#### Files Are Missing After Deployment

- **Check `.funcignore`**: May be excluding needed files
- **Check Oryx Build Logs**: In Azure Portal → Function App → Deployment Center → Logs
- Azure only deploys what's in git (staged changes) - ensure files are committed

### Alternative: OIDC Authentication (More Secure)

If you want to migrate from publish profiles to OIDC (recommended for production):

1. Create Azure Service Principal with federated credentials
2. Replace `publish-profile` with `azure/login@v1` action in workflow
3. Benefits: No stored secrets, better security, aligns with Terraform/IaC approach

For now, the publish profile method works and is simpler for personal projects.

### Benefits of Current Setup

- ✅ **Automated Testing**: Every push runs tests before deployment
- ✅ **Gated Deployment**: Tests must pass to deploy
- ✅ **Azure Handles Build**: Oryx ensures dependencies match runtime
- ✅ **Clean Deployments**: `.funcignore` keeps deployment package lean
- ✅ **Manual Override**: Can trigger deployment via workflow dispatch
