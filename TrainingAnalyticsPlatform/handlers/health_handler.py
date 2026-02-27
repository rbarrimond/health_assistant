"""Health check and plugin metadata handler."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Tuple, Any

logger = logging.getLogger(__name__)


class HealthHandler:
    """Handles health check and plugin metadata endpoints."""

    def __init__(self, storage, api_docs_dir: str):
        """Initialize handler with storage and API docs directory.

        Args:
            storage: StorageCoordinator instance for health checks
            api_docs_dir: Path to API documentation files directory
        """
        self.storage = storage
        self.api_docs_dir = api_docs_dir

    def check_health(self) -> Tuple[Dict[str, Any], int]:
        """Verify system health and dependencies.

        Returns:
            Tuple of (health_status_dict, status_code)
        """
        checks = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        status_code = 200

        try:
            # Lightweight operation to verify storage connectivity
            list(self.storage.infrastructure.service_client.list_tables(results_per_page=1))
            checks["storage"] = "ok"
        except Exception:  # pylint: disable=broad-except
            checks["storage"] = "degraded"
            checks["status"] = "degraded"
            status_code = 503

        return checks, status_code

    def get_plugin_manifest(
        self, base_url: str, env_overrides: Dict[str, str]
    ) -> Tuple[Dict[str, Any], int]:
        """Get ChatGPT plugin manifest with dynamic URLs.

        Args:
            base_url: The externally reachable base URL
            env_overrides: Dictionary of environment variable overrides
                - PLUGIN_LOGO_URL: Logo URL override
                - PLUGIN_CONTACT_EMAIL: Contact email override
                - PLUGIN_LEGAL_URL: Legal info URL override

        Returns:
            Tuple of (manifest_dict, status_code)
        """
        manifest_path = os.path.join(self.api_docs_dir, "ai-plugin.json")

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except FileNotFoundError:
            return {"error": "ai-plugin.json not found"}, 500
        except json.JSONDecodeError as exc:
            logger.error("ai-plugin.json invalid: %s", exc)
            return {"error": "ai-plugin.json invalid"}, 500

        # Populate dynamic metadata
        manifest.setdefault("api", {})["url"] = f"{base_url}/openapi.yaml"
        manifest["logo_url"] = env_overrides.get(
            "PLUGIN_LOGO_URL",
            f"{base_url}/logo.svg"
        ) or manifest.get(
            "logo_url",
            "https://via.placeholder.com/128.png?text=Health+Assistant"
        )

        manifest["contact_email"] = env_overrides.get(
            "PLUGIN_CONTACT_EMAIL",
            manifest.get(
                "contact_email",
                "rbarrimond+health-assistant@users.noreply.github.com"
            )
        )

        manifest["legal_info_url"] = env_overrides.get(
            "PLUGIN_LEGAL_URL",
            manifest.get(
                "legal_info_url",
                "https://github.com/rbarrimond/health_assistant/blob/main/README.md"
            )
        )

        return manifest, 200

    def get_openapi_spec(self, base_url: str) -> Tuple[str, int]:
        """Get OpenAPI spec with dynamic server URL.

        Args:
            base_url: The externally reachable base URL

        Returns:
            Tuple of (spec_yaml_string, status_code)
        """
        spec_path = os.path.join(self.api_docs_dir, "openapi.yaml")

        try:
            with open(spec_path, "r", encoding="utf-8") as f:
                spec_body = f.read()
        except FileNotFoundError:
            return "# openapi.yaml not found", 500

        # Replace placeholder server URL with actual base URL
        spec_body = spec_body.replace(
            "https://health-assistant.azurewebsites.net",
            base_url
        )

        return spec_body, 200

    def get_logo(self) -> Tuple[str, int]:
        """Get logo SVG content.

        Returns:
            Tuple of (svg_content, status_code)
        """
        logo_path = os.path.join(self.api_docs_dir, "logo.svg")

        try:
            with open(logo_path, "r", encoding="utf-8") as f:
                logo_body = f.read()
            return logo_body, 200
        except FileNotFoundError:
            return "<!-- logo.svg not found -->", 500
