"""Configuration and environment utilities."""

import os


class Config:
    """Azure Function configuration from environment."""

    # Azure Storage
    AZURE_STORAGE_CONNECTION_STRING = os.getenv("AzureWebJobsStorage")
    AZURE_STORAGE_ACCOUNT_URL = os.getenv("AZURE_STORAGE_ACCOUNT_URL")

    # Athlete config
    DEFAULT_ATHLETE_ID = os.getenv("DEFAULT_ATHLETE_ID", "rob")

    # FIT parsing - Heart Rate Zones
    HR_ZONE_BASIS = os.getenv("HR_ZONE_BASIS", "HRmax")  # HRmax, LTHR, or HRR
    HR_ZONE_REFERENCE_BPM = int(os.getenv("HR_ZONE_REFERENCE_BPM", "0")) or None
    HR_RESTING_BPM = int(os.getenv("HR_RESTING_BPM", "60"))  # For HRR method

    # FIT parsing - Power Zones
    DEFAULT_FTP = int(os.getenv("DEFAULT_FTP", "250"))
    DEFAULT_MAX_HR = int(os.getenv("DEFAULT_MAX_HR", "190"))

    # OneDrive
    ONEDRIVE_FOLDER_PATH = os.getenv("ONEDRIVE_FOLDER_PATH", "/Apps/HealthFit")

    @staticmethod
    def validate():
        """Validate required configuration is present."""
        if not Config.AZURE_STORAGE_CONNECTION_STRING and not Config.AZURE_STORAGE_ACCOUNT_URL:
            raise ValueError(
                "Must set AzureWebJobsStorage or AZURE_STORAGE_ACCOUNT_URL environment variable"
            )
