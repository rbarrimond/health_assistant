"""Tests for HealthHandler."""

# pylint: disable=line-too-long

from unittest.mock import Mock

import pytest

from TrainingAnalyticsPlatform.handlers import HealthHandler


class TestHealthHandler:
    """Test suite for HealthHandler."""

    @pytest.fixture
    def mock_storage(self):
        """Create mock WorkoutTableStorage."""
        return Mock()

    @pytest.fixture
    def temp_api_docs(self, tmp_path):
        """Create temporary API docs directory with test files."""
        api_docs = tmp_path / "api_docs"
        api_docs.mkdir()

        # Create ai-plugin.json
        plugin_json = api_docs / "ai-plugin.json"
        plugin_json.write_text('''{
            "schema_version": "v1",
            "name_for_human": "Health Assistant",
            "name_for_model": "health_assistant",
            "description_for_human": "Track workouts",
            "description_for_model": "Workout tracking system",
            "api": {"url": "PLACEHOLDER_URL"},
            "logo_url": "https://example.com/logo.svg",
            "contact_email": "default@example.com",
            "legal_info_url": "https://example.com/legal"
        }''')

        # Create openapi.yaml
        openapi_yaml = api_docs / "openapi.yaml"
        openapi_yaml.write_text('''openapi: 3.0.0
info:
  title: Health Assistant API
  version: 1.0.0
servers:
  - url: https://health-assistant.azurewebsites.net
paths:
  /health:
    get:
      summary: Health check
''')

        # Create logo.svg
        logo_svg = api_docs / "logo.svg"
        logo_svg.write_text('''<svg xmlns="http://www.w3.org/2000/svg">
  <circle cx="50" cy="50" r="40" fill="blue"/>
</svg>''')

        return str(api_docs)

    @pytest.fixture
    def handler(self, mock_storage, temp_api_docs):
        """Create handler instance with mocked dependencies."""
        return HealthHandler(mock_storage, temp_api_docs)

    def test_check_health_storage_ok(self, handler, mock_storage):
        """Test health check with working storage."""
        # Arrange
        mock_service_client = Mock()
        mock_service_client.list_tables.return_value = iter([{"name": "workouts"}])
        mock_storage.service_client = mock_service_client

        # Act
        result, status = handler.check_health()

        # Assert
        assert status == 200
        assert result["status"] == "healthy"
        assert result["storage"] == "ok"
        mock_service_client.list_tables.assert_called_once()

    def test_check_health_storage_degraded(self, handler, mock_storage):
        """Test health check with storage issues."""
        # Arrange
        mock_service_client = Mock()
        mock_service_client.list_tables.side_effect = Exception("Connection timeout")
        mock_storage.service_client = mock_service_client

        # Act
        result, status = handler.check_health()

        # Assert
        assert status == 503
        assert result["status"] == "degraded"
        assert result["storage"] == "degraded"

    def test_get_plugin_manifest_success(self, handler):
        """Test successful plugin manifest retrieval."""
        # Act
        result, status = handler.get_plugin_manifest(
            base_url="https://custom.example.com",
            env_overrides={}
        )

        # Assert
        assert status == 200
        assert result["name_for_human"] == "Health Assistant"
        assert result["api"]["url"] == "https://custom.example.com/openapi.yaml"
        # Handler uses base_url to construct default logo URL when no override
        assert result["logo_url"] == "https://custom.example.com/logo.svg"

    def test_get_plugin_manifest_with_env_overrides(self, handler):
        """Test plugin manifest with environment variable overrides."""
        # Arrange
        env_overrides = {
            "PLUGIN_LOGO_URL": "https://custom-logo.example.com/logo.png",
            "PLUGIN_CONTACT_EMAIL": "custom@example.com",
            "PLUGIN_LEGAL_URL": "https://custom.example.com/terms"
        }

        # Act
        result, status = handler.get_plugin_manifest(
            base_url="https://api.example.com",
            env_overrides=env_overrides
        )

        # Assert
        assert status == 200
        assert result["logo_url"] == "https://custom-logo.example.com/logo.png"
        assert result["contact_email"] == "custom@example.com"
        assert result["legal_info_url"] == "https://custom.example.com/terms"

    def test_get_plugin_manifest_fallback_to_file_values(self, handler):
        """Test plugin manifest falls back to base_url or file values when overrides are None."""
        # Arrange
        env_overrides = {
            "PLUGIN_LOGO_URL": None,  # Will use base_url default via or operator
            "PLUGIN_CONTACT_EMAIL": "override@example.com",
            "PLUGIN_LEGAL_URL": None  # env_overrides.get returns None (key exists)
        }

        # Act
        result, status = handler.get_plugin_manifest(
            base_url="https://example.com",
            env_overrides=env_overrides
        )

        # Assert
        assert status == 200
        assert result["logo_url"] == "https://example.com/logo.svg"  # base_url default via or operator
        assert result["contact_email"] == "override@example.com"  # Override value
        assert result["legal_info_url"] is None  # env_overrides.get returns None when key exists with None value

    def test_get_plugin_manifest_file_not_found(self, mock_storage):
        """Test plugin manifest when file doesn't exist."""
        # Arrange
        handler = HealthHandler(mock_storage, "/nonexistent/path")

        # Act
        result, status = handler.get_plugin_manifest(
            base_url="https://example.com",
            env_overrides={}
        )

        # Assert
        assert status == 500  # Handler returns 500 for file errors
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_get_plugin_manifest_invalid_json(self, mock_storage, tmp_path):
        """Test plugin manifest with invalid JSON."""
        # Arrange
        api_docs = tmp_path / "api_docs"
        api_docs.mkdir()
        plugin_json = api_docs / "ai-plugin.json"
        plugin_json.write_text("{ invalid json }")

        handler = HealthHandler(mock_storage, str(api_docs))

        # Act
        result, status = handler.get_plugin_manifest(
            base_url="https://example.com",
            env_overrides={}
        )

        # Assert
        assert status == 500
        assert "error" in result
        assert "invalid" in result["error"].lower()

    def test_get_openapi_spec_success(self, handler):
        """Test successful OpenAPI spec retrieval."""
        # Act
        spec_body, status = handler.get_openapi_spec("https://custom.example.com")

        # Assert
        assert status == 200
        assert "openapi: 3.0.0" in spec_body
        assert "https://custom.example.com" in spec_body
        # Original URL should be replaced
        assert "health-assistant.azurewebsites.net" not in spec_body

    def test_get_openapi_spec_url_replacement(self, handler):
        """Test OpenAPI spec URL replacement works correctly."""
        # Act
        spec_body, status = handler.get_openapi_spec("https://prod.example.com")

        # Assert
        assert status == 200
        assert "https://prod.example.com" in spec_body
        # Verify the replacement happened
        assert spec_body.count("https://prod.example.com") >= 1

    def test_get_openapi_spec_file_not_found(self, mock_storage):
        """Test OpenAPI spec when file doesn't exist."""
        # Arrange
        handler = HealthHandler(mock_storage, "/nonexistent/path")

        # Act
        spec_body, status = handler.get_openapi_spec("https://example.com")

        # Assert
        assert status == 500  # Handler returns 500 for file errors
        assert "not found" in spec_body.lower()

    def test_get_logo_success(self, handler):
        """Test successful logo retrieval."""
        # Act
        logo_body, status = handler.get_logo()

        # Assert
        assert status == 200
        assert "<svg" in logo_body
        assert "circle" in logo_body

    def test_get_logo_file_not_found(self, mock_storage):
        """Test logo when file doesn't exist."""
        # Arrange
        handler = HealthHandler(mock_storage, "/nonexistent/path")

        # Act
        logo_body, status = handler.get_logo()

        # Assert
        assert status == 500  # Handler returns 500 for file errors
        assert "not found" in logo_body.lower()

    def test_check_health_no_storage_client_attribute(self, handler, mock_storage):
        """Test health check when storage doesn't have service_client."""
        # Arrange
        delattr(mock_storage, 'service_client')

        # Act
        result, status = handler.check_health()

        # Assert
        assert status == 503
        assert result["status"] == "degraded"
        assert result["storage"] == "degraded"

    def test_get_plugin_manifest_sets_default_logo_url(self, handler):
        """Test plugin manifest sets default logo URL when base_url provided."""
        # Act
        result, status = handler.get_plugin_manifest(
            base_url="https://api.example.com",
            env_overrides={"logo_url": None}
        )

        # Assert
        assert status == 200
        # Should fall back to default from file (not generate from base_url)
        assert "logo" in result["logo_url"]
