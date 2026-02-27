"""Async webhook processor for Withings measurement data.

This module processes queued Withings webhook notifications in the background.
It fetches measurement data from the Withings API and stores it in the Physiometrics table.

To deploy this as an Azure Queue-triggered function, add the following to function_app.py:

@app.queue_trigger(arg_name="msg", queue_name="withings-webhooks",
                   connection="AzureWebJobsStorage")
def process_withings_webhook(msg: func.QueueMessage) -> None:
    process_webhook_async(msg.get_body().decode('utf-8'))
"""

import json
import logging
from datetime import datetime, timezone

from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator
from TrainingAnalyticsPlatform.integrations.withings_client import WithingsClient

logger = logging.getLogger(__name__)


def _parse_webhook_message(message_body: str) -> dict:
    webhook_data = json.loads(message_body)
    athlete_id = webhook_data.get("athlete_id")
    if not athlete_id:
        raise ValueError("Missing athlete_id in webhook message")

    return {
        "userid": webhook_data["userid"],
        "startdate": int(webhook_data["startdate"]),
        "enddate": int(webhook_data["enddate"]),
        "athlete_id": athlete_id,
    }


def _ensure_access_token(storage: StorageCoordinator, client: WithingsClient,
                         athlete_id: str, userid: str) -> str:
    token_data = storage.oauth_tokens.get_withings_tokens(athlete_id)
    if not token_data:
        raise ValueError(f"No Withings tokens found for athlete {athlete_id}")

    access_token = token_data["access_token"]
    expires_at = datetime.fromisoformat(
        token_data["expires_at_utc"].replace("Z", "+00:00")
    )

    if datetime.now(timezone.utc) < expires_at:
        return access_token

    logger.info("Access token expired, refreshing...")
    refreshed = client.refresh_access_token(token_data["refresh_token"])
    storage.oauth_tokens.refresh_withings_token(
        athlete_id=athlete_id,
        withings_userid=userid,
        new_access_token=refreshed["access_token"],
        new_refresh_token=refreshed["refresh_token"],
        expires_in=refreshed["expires_in"]
    )
    logger.info("Access token refreshed successfully")
    return refreshed["access_token"]


def _store_measurements(storage: StorageCoordinator, athlete_id: str, measurements: list) -> None:
    for measurement in measurements:
        measured_at = datetime.fromisoformat(measurement["measured_at"])
        effective_date = measured_at.date().isoformat()

        physio_data = {}
        if "weight_kg" in measurement:
            physio_data["weight_kg"] = measurement["weight_kg"]
        if "fat_mass_kg" in measurement:
            physio_data["fat_mass_kg"] = measurement["fat_mass_kg"]
        if "muscle_mass_kg" in measurement:
            physio_data["muscle_mass_kg"] = measurement["muscle_mass_kg"]
        if "bone_mass_kg" in measurement:
            physio_data["bone_mass_kg"] = measurement["bone_mass_kg"]
        if "body_fat_pct" in measurement:
            physio_data["body_fat_pct"] = measurement["body_fat_pct"]
        if "visceral_fat_index" in measurement:
            physio_data["visceral_fat_index"] = measurement["visceral_fat_index"]
        if "metabolic_age_years" in measurement:
            physio_data["metabolic_age_years"] = measurement["metabolic_age_years"]

        storage.physiometrics.store_physiometrics(
            athlete_id=athlete_id,
            physiometrics_data=physio_data,
            effective_date=effective_date,
            data_source="withings"
        )

        logger.info(
            "Stored Withings measurement for %s on %s: weight=%s kg",
            athlete_id, effective_date, physio_data.get("weight_kg")
        )


def process_webhook_async(message_body: str) -> None:
    """Process a Withings webhook notification asynchronously."""
    try:
        webhook_data = _parse_webhook_message(message_body)
        userid = webhook_data["userid"]
        startdate = webhook_data["startdate"]
        enddate = webhook_data["enddate"]
        athlete_id = webhook_data["athlete_id"]

        logger.info(
            "Processing Withings webhook for athlete %s (userid: %s)",
            athlete_id, userid
        )

        storage = StorageCoordinator()
        client = WithingsClient()

        if storage.webhooks.webhook_already_processed(athlete_id, userid, str(enddate)):
            logger.info("Webhook already processed, skipping")
            return

        try:
            access_token = _ensure_access_token(storage, client, athlete_id, userid)
        except Exception as token_error:  # pylint: disable=broad-exception-caught
            logger.error("Token handling failed: %s", token_error)
            return

        measurements = client.fetch_measurements(access_token, startdate, enddate)
        logger.info("Fetched %d measurements from Withings", len(measurements))

        _store_measurements(storage, athlete_id, measurements)

        storage.webhooks.mark_webhook_processed(athlete_id, userid, str(enddate))
        logger.info("Webhook processing complete")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error processing Withings webhook: %s", e, exc_info=True)
        raise  # Re-raise to trigger Azure Functions retry
