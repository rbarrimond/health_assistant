"""Withings OAuth and webhook handler."""

import logging
import os
from typing import Any, Dict, Tuple

from TrainingAnalyticsPlatform.integrations.withings_client import WithingsClient
from TrainingAnalyticsPlatform.platform.exceptions import HealthAssistantError, ValidationError
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator


logger = logging.getLogger(__name__)

# Constants
HTML_CONTENT_TYPE = "text/html"
ERROR_HTML = "<html><body><h1>Error</h1><p>Missing authorization code or state</p></body></html>"


class WithingsHandler:
    """Handles Withings OAuth and webhook operations."""

    def __init__(self, withings_client: WithingsClient, storage: StorageCoordinator):
        """Initialize handler with Withings client and storage dependencies."""
        self.client = withings_client
        self.storage = storage

    def get_authorization_url(self, athlete_id: str) -> Tuple[Dict[str, Any], int]:
        """Generate Withings OAuth authorization URL.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": "athlete_id parameter required"}, 400

        try:
            auth_url, _ = self.client.get_authorization_url(athlete_id)

            return {
                "authorization_url": auth_url,
                "instructions": "Open this URL in your browser to authorize Withings access",
                "athlete_id": athlete_id
            }, 200
        except ValidationError as exc:
            logger.error("Invalid Withings authorization request: %s", exc, exc_info=True)
            return {"error": str(exc)}, 400
        except HealthAssistantError as exc:
            logger.error("Error generating Withings auth URL: %s", exc, exc_info=True)
            return {"error": "Failed to generate authorization URL"}, 500
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error generating Withings auth URL: %s", exc, exc_info=True)
            return {"error": "Failed to generate authorization URL"}, 500

    def handle_oauth_callback(
        self,
        code: str,
        state: str,
        webhook_base_url: str
    ) -> Tuple[str, int, str]:
        """Process OAuth callback and store tokens.

        Args:
            code: OAuth authorization code
            state: OAuth state parameter
            webhook_base_url: Base URL for constructing webhook callback URL

        Returns:
            Tuple of (HTML response, status_code, content_type)
        """
        if not code or not state:
            return (
                ERROR_HTML,
                400,
                HTML_CONTENT_TYPE
            )

        try:
            token_data = self.client.exchange_auth_code(code, state)

            self.storage.oauth_tokens.store_withings_tokens(
                athlete_id=token_data["athlete_id"],
                withings_userid=str(token_data["userid"]),
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                expires_in=token_data["expires_in"],
                scope=token_data["scope"]
            )

            callback_url = os.getenv(
                "WITHINGS_WEBHOOK_URL",
                f"{webhook_base_url}/api/withings/webhook"
            )
            self.client.subscribe_to_notifications(
                access_token=token_data["access_token"],
                callback_url=callback_url
            )

            logger.info(
                "Successfully connected Withings for athlete %s (userid: %s)",
                token_data["athlete_id"], token_data["userid"]
            )

            success_html = f"""<html>
                <body>
                    <h1>Success!</h1>
                    <p>Withings connected for athlete {token_data['athlete_id']}.</p>
                    <p>Weight measurements will now sync automatically.</p>
                    <p>You can close this window and return to the chat.</p>
                </body>
                </html>"""

            return success_html, 200, HTML_CONTENT_TYPE

        except ValidationError as exc:
            logger.error("Invalid Withings callback payload: %s", exc, exc_info=True)
            error_html = (
                "<html><body><h1>Error</h1>"
                f"<p>{exc}</p>"
                "</body></html>"
            )
            return error_html, 400, HTML_CONTENT_TYPE
        except HealthAssistantError as exc:
            logger.error("Error in Withings callback: %s", exc, exc_info=True)
            error_html = (
                "<html><body><h1>Error</h1>"
                f"<p>Failed to connect Withings account: {exc}</p>"
                "</body></html>"
            )
            return error_html, 500, HTML_CONTENT_TYPE
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error in Withings callback: %s", exc, exc_info=True)
            error_html = (
                "<html><body><h1>Error</h1>"
                f"<p>Failed to connect Withings account: {exc}</p>"
                "</body></html>"
            )
            return error_html, 500, HTML_CONTENT_TYPE

    def process_webhook(
        self,
        userid: str,
        appli: str,
        startdate: str,
        enddate: str
    ) -> Tuple[str, int]:
        """Process Withings webhook notification.

        Args:
            userid: Withings user ID
            appli: Notification type (1 = weight)
            startdate: Unix timestamp start
            enddate: Unix timestamp end

        Returns:
            Tuple of ("OK", status_code)
        """
        try:
            if not all([userid, appli, startdate, enddate]):
                logger.warning("Invalid Withings webhook payload: missing fields")
                return "Missing required fields", 400

            if appli != "1":
                logger.info("Ignoring non-weight notification (appli=%s)", appli)
                return "OK", 200

            logger.info(
                "Received Withings webhook: userid=%s, startdate=%s, enddate=%s",
                userid, startdate, enddate
            )

            # Queue for async processing (Azure Queue integration pending)
            # For now, just acknowledge receipt

            return "OK", 200

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error processing Withings webhook: %s", exc, exc_info=True)
            return "Temporary processing failure", 503
