"""Custom exceptions for health assistant handlers."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


class HealthAssistantError(Exception):
    """Base exception for all health assistant errors."""

    error_code = "HEALTH_ASSISTANT_ERROR"
    status_code = 500

    def __init__(self, message: Optional[str] = None):
        super().__init__(message or self.__class__.__name__)

    def to_response(
        self,
        *,
        extra: Optional[Dict[str, Any]] = None,
        include_message_alias: bool = False,
    ) -> Tuple[Dict[str, Any], int]:
        """Convert the exception to a standardized API response format."""
        body: Dict[str, Any] = {
            "status": "error",
            "error_code": self.error_code,
            "error": str(self),
        }
        if include_message_alias:
            body["message"] = str(self)
        if extra:
            body.update(extra)
        return body, self.status_code


class ValidationError(HealthAssistantError):
    """Raised when input validation fails."""

    error_code = "VALIDATION_ERROR"
    status_code = 400


class StorageError(HealthAssistantError):
    """Raised when storage operations fail."""

    error_code = "STORAGE_ERROR"
    status_code = 500


class ConfigError(HealthAssistantError):
    """Raised when configuration is invalid or missing."""

    error_code = "CONFIG_ERROR"
    status_code = 500


class SyncError(HealthAssistantError):
    """Raised when sync operations fail."""

    error_code = "SYNC_ERROR"
    status_code = 500


class AuthError(HealthAssistantError):
    """Raised when authentication or authorization fails."""

    error_code = "AUTH_ERROR"
    status_code = 401


class ExternalServiceError(HealthAssistantError):
    """Raised when external service (Withings, OneDrive, etc.) fails."""

    error_code = "EXTERNAL_SERVICE_ERROR"
    status_code = 502


class WorkoutTypeResolutionError(HealthAssistantError):
    """Raised when Apple workout type resolution fails unexpectedly."""

    error_code = "WORKOUT_TYPE_RESOLUTION_ERROR"
    status_code = 500


class IngestionIdResolutionError(HealthAssistantError):
    """Raised when ingestion_id cannot be resolved from source-specific inputs."""

    error_code = "INGESTION_ID_RESOLUTION_FAILED"
    status_code = 422


class WorkoutIdCalculationError(HealthAssistantError):
    """Raised when semantic workout_id calculation fails."""

    error_code = "WORKOUT_ID_CALCULATION_FAILED"
    status_code = 422


class FitParsingError(HealthAssistantError):
    """Raised when FIT payload bytes cannot be parsed into FIT messages."""

    error_code = "FIT_PARSING_FAILED"
    status_code = 422


class DeviceFilteredError(HealthAssistantError):
    """Raised when a FIT file is rejected by device filtration policy."""

    error_code = "DEVICE_FILTERED"
    status_code = 400

    def __init__(
        self,
        message: str,
        *,
        device_name: Optional[str] = None,
        device_source_type: Optional[str] = None,
        manufacturer_code: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.device_name = device_name
        self.device_source_type = device_source_type
        self.manufacturer_code = manufacturer_code
        self.reason = reason

    def to_response(
        self,
        *,
        extra: Optional[Dict[str, Any]] = None,
        include_message_alias: bool = False,
    ) -> Tuple[Dict[str, Any], int]:
        body: Dict[str, Any] = {
            "status": "filtered",
            "error_code": self.error_code,
            "error": str(self),
            "reason": self.reason or str(self),
            "device_name": self.device_name,
            "device_source_type": self.device_source_type,
            "manufacturer_code": self.manufacturer_code,
        }
        if include_message_alias:
            body["message"] = str(self)
        if extra:
            body.update(extra)
        return body, self.status_code


class PreprocessingError(HealthAssistantError):
    """Base exception for file preprocessing failures.
    
    Raised when file preprocessing operations (decompression, extraction,
    format validation) fail before FIT parsing can begin.
    """

    error_code = "PREPROCESSING_ERROR"
    status_code = 422


class CompressionError(PreprocessingError):
    """Raised when compression format detection or decompression fails.
    
    This includes gzip decompression failures, ZIP extraction failures,
    and unrecognized compression formats.
    """

    error_code = "COMPRESSION_ERROR"
    status_code = 422


class InvalidFileFormatError(PreprocessingError):
    """Raised when FIT header validation fails after preprocessing.
    
    Indicates that preprocessing succeeded but the resulting bytes
    do not contain a valid FIT file header.
    """

    error_code = "INVALID_FILE_FORMAT"
    status_code = 422
