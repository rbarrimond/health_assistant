"""Configuration and environment utilities."""

import os
from typing import Optional


class Config:
    """Azure Function configuration from environment."""

    # Azure Storage
    AZURE_STORAGE_CONNECTION_STRING = os.getenv("AzureWebJobsStorage")
    AZURE_STORAGE_ACCOUNT_URL = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    
    # Athlete config
    DEFAULT_ATHLETE_ID = os.getenv("DEFAULT_ATHLETE_ID", "rob")
    
    # FIT parsing
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
