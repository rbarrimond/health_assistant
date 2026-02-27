"""Device source classification utilities for FIT ingestion.

This module classifies devices as Apple Watch (true source) or HealthKit synced
(via iPhone) based on FIT file metadata and device_name signals. Uses FIT
manufacturer/product codes from code_mappings for reliability, falling back to
device_name string matching when codes unavailable.

The classification enables filtering of synced vs. true-source workouts at the
ingestion boundary.

References:
- code_mappings.py: FIT manufacturer and product code mappings
- HealthFit exports device_name="iPhone" as sentinel for HealthKit synced workouts
- Apple device classification via FIT file_manufacturer and device product codes
"""

from typing import Optional

from .code_mappings import (
    APPLE_PRODUCT_CODES,
)


class FitDevice:
    """Classify device source for FIT files (true source vs. HealthKit synced).
    
    Methods are stateless and accept raw FIT metadata fields.
    Classification hierarchy:
    1. FIT product codes (authoritative for Apple devices)
    2. FIT manufacturer code (fallback check)
    3. device_name string matching (final fallback)
    
    Classifies as:
    - "apple_watch": True source (native Apple Watch export)
    - "healthkit_synced": Synced via HealthKit (iPhone sentinel)
    - "unknown": Unclassifiable
    """

    @staticmethod
    def is_healthkit_synced(
        device_name: Optional[str],
        device_manufacturer_code: Optional[int] = None,
        device_product_code: Optional[int] = None,
    ) -> bool:
        """Detect if workout was synced into HealthKit from another app.
        
        HealthFit exports synced workouts with device_name="iPhone" (sentinel value).
        Direct Apple Watch exports have device_name containing "Apple Watch" or "Watch".
        Uses FIT product codes if available for authoritative classification.
        
        Args:
            device_name: FIT device_info.device_name field (e.g., "iPhone", "Apple Watch Series 5 40mm (GPS)")
            device_manufacturer_code: FIT device_info.manufacturer code (int)
            device_product_code: FIT device_info.product code (int)
            
        Returns:
            True if device is "iPhone" (synced via HealthKit)
            False if Apple Watch (true source workout)
            False if device_name missing/None (conservatively assume true source)
        """
        # Check product code first (most reliable)
        if device_product_code is not None:
            product_name = APPLE_PRODUCT_CODES.get(
                device_product_code, ""
            ).lower()
            if "iphone" in product_name:
                return True
            if "watch" in product_name:
                return False

        # Fallback to device_name string matching
        if device_name is None:
            return False

        device_lower = device_name.lower()
        return "iphone" in device_lower

    @staticmethod
    def is_apple_watch_source(
        device_name: Optional[str],
        device_manufacturer_code: Optional[int] = None,
        device_product_code: Optional[int] = None,
    ) -> bool:
        """Check if workout originated from Apple Watch (not synced via HealthKit).
        
        Args:
            device_name: FIT device_info.device_name field
            device_manufacturer_code: FIT device_info.manufacturer code
            device_product_code: FIT device_info.product code
            
        Returns:
            True if Apple Watch is the source
            False if HealthKit synced (iPhone sentinel)
        """
        return not FitDevice.is_healthkit_synced(
            device_name=device_name,
            device_manufacturer_code=device_manufacturer_code,
            device_product_code=device_product_code,
        )

    @staticmethod
    def device_source_type(
        device_name: Optional[str],
        device_manufacturer_code: Optional[int] = None,
        device_product_code: Optional[int] = None,
    ) -> str:
        """Classify device source for downstream filtering.
        
        Args:
            device_name: FIT device_info.device_name field
            device_manufacturer_code: FIT device_info.manufacturer code
            device_product_code: FIT device_info.product code
            
        Returns:
            "apple_watch" - Native Apple Watch export (true source)
            "healthkit_synced" - Synced from another app via HealthKit (iPhone sentinel)
            "unknown" - Device not detected or missing
        """
        if device_name is None and device_product_code is None:
            return "unknown"

        # Check product code first (most reliable)
        if device_product_code is not None:
            product_name = APPLE_PRODUCT_CODES.get(
                device_product_code, ""
            ).lower()
            if "iphone" in product_name:
                return "healthkit_synced"
            if "watch" in product_name:
                return "apple_watch"

        # Fallback to device_name string matching
        if device_name is None:
            return "unknown"

        device_lower = device_name.lower()

        if "iphone" in device_lower:
            return "healthkit_synced"
        if "watch" in device_lower:
            return "apple_watch"

        return "unknown"
