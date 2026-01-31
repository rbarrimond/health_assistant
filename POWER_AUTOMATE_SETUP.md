# OneDrive Personal OAuth + Sync Guide

> **Source of Truth**: See [WORKOUT_SCHEMA.md](./WORKOUT_SCHEMA.md) for the complete data model and required fields. This document describes the ingestion procedure.

This guide explains how to sync HealthFit exports from **OneDrive Personal** into the Health Assistant Azure Function using **delegated OAuth** (no Power Automate).

## Prerequisites

- OneDrive Personal account
- HealthFit exports stored in `/Apps/HealthFit` (or your chosen OneDrive folder)
- Azure Function deployed with the OneDrive endpoints

## Overview

```text
OneDrive Personal (/Apps/HealthFit)
    ↓
OAuth 2.0 (delegated)
    ↓
Azure Function (Timer + HTTP sync via Microsoft Graph)
    ↓
FIT Parser → Metrics → Azure Table Storage
```

## Required App Registration

Create a Microsoft app registration that supports **consumer accounts**:

1. Go to Azure Portal → App registrations → New registration
2. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**
3. Redirect URI (web): `https://<FUNCTION_APP>.azurewebsites.net/api/onedrive/callback`
4. Create a **client secret**

Record the **Client ID** and **Client Secret**.

## Required Function App Settings

Set these in your Function App configuration:

- `ONEDRIVE_CLIENT_ID`
- `ONEDRIVE_CLIENT_SECRET`
- `ONEDRIVE_REDIRECT_URI` (same as the redirect URI above)
- `ONEDRIVE_SCOPES` (default: `Files.ReadWrite offline_access`)
- `ONEDRIVE_FOLDER_PATH` (default: `/Apps/HealthFit`)
- `ONEDRIVE_SYNC_LOOKBACK_DAYS` (default: `30`)

## Step 1: Authorize OneDrive

Generate an authorization URL:

```bash
curl "https://<FUNCTION_APP>.azurewebsites.net/api/onedrive/authorize?athlete_id=rob&code=<FUNCTION_KEY>"
```

Open the `authorization_url` in a browser and sign in. On success, the callback stores refresh tokens.

## Step 2: Run Sync

### Manual Sync (HTTP)

```bash
curl -X POST "https://<FUNCTION_APP>.azurewebsites.net/api/onedrive/sync?code=<FUNCTION_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"days": 30, "athlete_id": "rob"}'
```

### Automatic Sync (Timer)

The timer runs hourly and uses `ONEDRIVE_SYNC_LOOKBACK_DAYS`.

## Troubleshooting

- **Authorization failed**: verify client ID/secret and redirect URI.
- **No tokens stored**: complete the authorize/callback step.
- **No files found**: check `ONEDRIVE_FOLDER_PATH` and verify files exist.
