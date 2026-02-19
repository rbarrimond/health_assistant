# pylint: disable=line-too-long
"""Shared constants for HTTP API and plugin metadata.

This module contains platform-level configuration used by the HTTP API endpoints
and plugin system. It is kept separate from analytics constants (TrainingAnalyticsPlatform/models/constants.py)
to maintain modularity: the analytics engine can be used independently without
loading HTTP/plugin infrastructure, and each module's constants are colocated with their usage context.

Scope: Platform layer (HTTP API, plugin system, external interfaces)
Used by: function_app.py, utils.py, http_utils.py, and HTTP handler tests
"""

import os

JSON_CONTENT_TYPE = "application/json"
HTML_CONTENT_TYPE = "text/html"
TEXT_PLAIN_CONTENT_TYPE = "text/plain"
INTERNAL_SERVER_ERROR = "Internal server error"

# Error messages
ERR_MISSING_ATHLETE_ID = "Missing required parameter: athlete_id"
ERR_ATHLETE_ID_REQUIRED = "athlete_id parameter required"
ERR_INVALID_JSON = "Invalid JSON payload"
ERR_VALIDATION = "Validation error: %s"

# Plugin metadata environment variables
ENV_API_DOCS_DIR = "API_DOCS_DIR"
ENV_PUBLIC_BASE_URL = "PUBLIC_BASE_URL"
ENV_PLUGIN_LOGO_URL = "PLUGIN_LOGO_URL"
ENV_PLUGIN_CONTACT_EMAIL = "PLUGIN_CONTACT_EMAIL"
ENV_PLUGIN_LEGAL_URL = "PLUGIN_LEGAL_URL"

# Plugin metadata defaults
DEFAULT_LOGO_URL = "https://via.placeholder.com/128.png?text=Health+Assistant"
DEFAULT_CONTACT_EMAIL = "rbarrimond+health-assistant@users.noreply.github.com"
DEFAULT_LEGAL_URL = "https://github.com/rbarrimond/health_assistant/blob/main/README.md"

# API documentation paths
API_DOCS_DIR = os.getenv(ENV_API_DOCS_DIR, os.path.join(
    os.path.dirname(__file__), "..", "api_docs"))
PLUGIN_MANIFEST_PATH = os.path.join(API_DOCS_DIR, "ai-plugin.json")
OPENAPI_SPEC_PATH = os.path.join(API_DOCS_DIR, "openapi.yaml")
