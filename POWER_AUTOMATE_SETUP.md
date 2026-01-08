# Power Automate Integration Guide

This guide explains how to set up a Power Automate flow to monitor OneDrive and trigger the FIT file processor Azure Function.

## Prerequisites

- Power Automate subscription
- OneDrive folder: `/Apps/HealthFit/` containing FIT files
- Azure Function deployed with HTTP trigger endpoint
- Azure Function key for authentication

## Power Automate Flow Setup

### Trigger: OneDrive File Monitor

1. Create new cloud flow → Automated cloud flow
2. Trigger: "When a file is created (properties only)"
   - Location: Your OneDrive
   - Folder: `/Apps/HealthFit`

### Action 1: Get file content

1. Add action → "Get file content"
   - File: `{Id}` from trigger

### Action 2: Convert to Base64

1. Add action → "Compose"
   - Input: `base64(outputs('Get_file_content')?['body'])`
   - Save as: compose_base64

### Action 3: Get file metadata

1. Add action → "Get file properties"
   - File: `{Id}` from trigger
   - Save outputs

### Action 4: Call Azure Function

1. Add action → "HTTP"
   - Method: POST
   - URI: `https://<FUNCTION_APP_NAME>.azurewebsites.net/api/process_fit?code=<FUNCTION_KEY>`
   - Headers:

     ```
     Content-Type: application/json
     ```

   - Body:

     ```json
     {
       "athlete_id": "rob",
       "source_item_id": "@{outputs('Get_file_properties')?['body/id']}",
       "source_file_name": "@{outputs('Get_file_properties')?['body/name']}",
       "source_file_path": "@{outputs('Get_file_properties')?['body/path']}",
       "source_drive_id": "@{outputs('Get_file_properties')?['body/parentReference/driveId']}",
       "source_etag": "@{outputs('Get_file_properties')?['body/eTag']}",
       "file_size_bytes": "@{outputs('Get_file_properties')?['body/size']}",
       "file_content_b64": "@{outputs('compose_base64')}"
     }
     ```

### Action 5: Handle Response (Optional)

1. Add condition → Check response status
   - If success (200-299): Log to Application Insights or send notification
   - If error: Send email alert or log to Azure Blob

## Testing the Flow

1. Manually upload a FIT file to `/Apps/HealthFit/`
2. Trigger the flow
3. Check Azure Table Storage for new Workouts entry
4. Verify Application Insights logs

## Error Handling

The function returns:

- **200**: Success - `{"status": "success", "workout_id": "...", ...}`
- **400**: Validation error - `{"error": "Missing required fields: ..."}`
- **409**: Already processed - `{"status": "skipped", "reason": "File already processed"}`
- **500**: Server error - `{"error": "Failed to process FIT file: ..."}`

## Idempotency

The function checks `IngestionState` table before processing:

- **Primary key**: `source_item_id` (recommended - OneDrive itemId)
- **Fallback**: `file_sha256` hash

If a file is re-uploaded with same `itemId`, it will be skipped to prevent duplicates.

## Monitoring

- Check **Application Insights** for detailed logs
- Monitor **IngestionState** table for failed ingestions
- Set up alert on function errors

## OneDrive Graph Integration (Alternative)

Instead of Power Automate, you can use a timer-triggered function with Microsoft Graph:

```python
# Timer trigger every hour to check for new files
def check_onedrive_changes():
    graph_client = GraphServiceClient(credential=DefaultAzureCredential())
    
    # List files in /Apps/HealthFit with recent changes
    items = graph_client.me.drive.root.children.get()
    
    for item in items.value:
        if item.name.endswith('.fit'):
            # Download and process
```

This requires:

- Microsoft Graph SDK: `pip install msgraph-sdk`
- Graph permissions: `Files.Read` scope
