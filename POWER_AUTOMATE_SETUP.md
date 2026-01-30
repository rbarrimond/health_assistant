# iCloud Drive Sync Guide

> **Source of Truth**: See [WORKOUT_SCHEMA.md](./WORKOUT_SCHEMA.md) for the complete data model and required fields. This document describes the ingestion procedure.

This guide explains how to sync HealthFit exports from **iCloud Drive** into the Health Assistant Azure Function.

## Prerequisites

- iCloud Drive enabled
- Apple ID with an **app-specific password**
- HealthFit exports stored in `/HealthFit` (or your chosen iCloud folder)
- Azure Function deployed with HTTP + Timer triggers

## Overview

The system syncs iCloud Drive via **WebDAV** on a schedule (hourly) and can be triggered manually.

```text
iCloud Drive (/HealthFit)
    ↓
Azure Functions (Timer + HTTP sync)
    ↓
FIT Parser → Metrics → Azure Table Storage
```

## Required Environment Variables

Set these in your Function App configuration (or `local.settings.json` for local dev):

- `ICLOUD_WEBDAV_URL`: iCloud WebDAV base URL (e.g., `https://pXX-webdav.icloud.com`)
- `ICLOUD_USERNAME`: Apple ID (email)
- `ICLOUD_APP_PASSWORD`: app-specific password
- `ICLOUD_FOLDER_PATH`: Folder path in iCloud Drive (default: `/HealthFit`)
- `ICLOUD_SYNC_LOOKBACK_DAYS`: Default lookback window (default: `30`)

## How to Find Your iCloud WebDAV URL

Apple assigns a WebDAV host like `https://pXX-webdav.icloud.com`. To discover yours:

1. Sign in to iCloud in a browser.
2. Open iCloud Drive.
3. Use a network inspector (browser dev tools) and look for a request to a `webdav.icloud.com` host.
4. Use that host value as `ICLOUD_WEBDAV_URL`.

If you already use a WebDAV client, it will often reveal the server URL after login.

## Manual Sync (HTTP)

Trigger a sync for the last 30 days:

```bash
curl -X POST "https://<FUNCTION_APP>.azurewebsites.net/api/icloud/sync?code=<FUNCTION_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"days": 30}'
```

The response includes counts for `ingested`, `skipped`, and `failed` items.

## Automatic Sync (Timer)

The timer trigger runs hourly and uses `ICLOUD_SYNC_LOOKBACK_DAYS` to determine how far back to scan.

## File Types

Currently ingested:
- `.fit`
- `.fit.gz` (automatically decompressed)

Other formats (`.gpx`, `.csv`, `.tcx`) are ignored for now.

## Troubleshooting

- **Authentication failed**: confirm `ICLOUD_USERNAME` and app-specific password.
- **No files found**: check `ICLOUD_FOLDER_PATH` and verify files exist in iCloud Drive.
- **Sync errors**: check Function App logs in Application Insights.

## Legacy OneDrive/Power Automate (Deprecated)

Older deployments used OneDrive + Power Automate. If you still need that flow, keep the old payload format but use the current ingestion endpoint.
