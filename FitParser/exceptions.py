"""Custom exceptions for health assistant handlers."""


class HealthAssistantError(Exception):
    """Base exception for all health assistant errors."""


class ValidationError(HealthAssistantError):
    """Raised when input validation fails."""


class StorageError(HealthAssistantError):
    """Raised when storage operations fail."""


class ConfigError(HealthAssistantError):
    """Raised when configuration is invalid or missing."""


class SyncError(HealthAssistantError):
    """Raised when sync operations fail."""


class AuthError(HealthAssistantError):
    """Raised when authentication or authorization fails."""


class ExternalServiceError(HealthAssistantError):
    """Raised when external service (Withings, OneDrive, etc.) fails."""
