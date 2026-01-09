"""Logging configuration for Azure Functions."""

import logging


def setup_logging():
    """Configure logging for the function app."""
    # Get the default function logger
    logger = logging.getLogger("azure.functions")
    logger.setLevel(logging.INFO)
    
    # Add console handler with format
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(console)
    
    return logger
