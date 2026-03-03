#!/bin/bash
# Setup Azure infrastructure for wellness ingestion
# Creates: Tables (Physiometrics, TrainingState, SourceIngestionState), Blob container (external-sources)

set -e

RESOURCE_GROUP="${RESOURCE_GROUP:-health-assistant-rg}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-healthassistantstore}"

echo "=========================================="
echo "Azure Wellness Ingestion Setup"
echo "=========================================="
echo "Resource Group: $RESOURCE_GROUP"
echo "Storage Account: $STORAGE_ACCOUNT"
echo ""

# Check if resource group exists
if ! az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
    echo "❌ Resource group not found: $RESOURCE_GROUP"
    echo "Create it with: az group create --name $RESOURCE_GROUP --location eastus"
    exit 1
fi

# Check if storage account exists
if ! az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    echo "❌ Storage account not found: $STORAGE_ACCOUNT"
    echo "Create it with: az storage account create --name $STORAGE_ACCOUNT --resource-group $RESOURCE_GROUP --location eastus --sku Standard_LRS"
    exit 1
fi

echo "✅ Storage account found: $STORAGE_ACCOUNT"
echo ""

# Get storage account connection string
CONNECTION_STRING=$(az storage account show-connection-string --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" -o tsv)
export AZURE_STORAGE_CONNECTION_STRING="$CONNECTION_STRING"

echo "========== Creating Tables =========="

# Create Physiometrics table
echo "Creating Physiometrics table..."
az storage table create --name Physiometrics --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" 2>/dev/null || echo "  (table may already exist)"

# Create TrainingState table
echo "Creating TrainingState table..."
az storage table create --name TrainingState --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" 2>/dev/null || echo "  (table may already exist)"

# Create SourceIngestionState table
echo "Creating SourceIngestionState table..."
az storage table create --name SourceIngestionState --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" 2>/dev/null || echo "  (table may already exist)"

echo ""
echo "========== Creating Blob Containers =========="

# Create external-sources container
echo "Creating external-sources container..."
az storage container create --name external-sources --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" 2>/dev/null || echo "  (container may already exist)"

# Create workouts container (if not exists)
echo "Creating workouts container..."
az storage container create --name workouts --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" 2>/dev/null || echo "  (container may already exist)"

# Create backups container (if not exists)
echo "Creating backups container..."
az storage container create --name backups --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" 2>/dev/null || echo "  (container may already exist)"

echo ""
echo "========== Verification =========="

# List tables
echo "Tables:"
az storage table list --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" -o table

echo ""
echo "Blob containers:"
az storage container list --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" -o table

echo ""
echo "✅ Azure infrastructure setup complete!"
echo ""
echo "Configuration Summary:"
echo "  Storage Account: $STORAGE_ACCOUNT"
echo "  Tables: Physiometrics, TrainingState, SourceIngestionState"
echo "  Containers: external-sources, workouts, backups"
echo ""
echo "Update your local.settings.json with:"
echo "  \"AzureWebJobsStorage\": \"$CONNECTION_STRING\""
echo ""
