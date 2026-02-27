"""Device source classification utilities for FIT ingestion.

This module classifies devices as Apple Watch (true source) or HealthKit synced
(via iPhone) based on FIT file metadata and device_name signals.

Classification uses device_name string matching. The FIT SDK does not provide
Apple product enums, so Apple device classification remains string-based.

The classification enables filtering of synced vs. true-source workouts at the
ingestion boundary.

References:
- HealthFit exports device_name="iPhone" as sentinel for HealthKit synced workouts
- Apple Watch exports have device_name containing "Apple Watch" or "Watch"
"""

from typing import Optional


class FitDevice:
    """Classify device source for FIT files (true source vs. HealthKit synced).
    
    Methods are stateless and accept raw FIT metadata fields.
    Classification strategy: device_name string matching.
    
    Apple devices do not have FIT product enums, so product code validation
    is not viable for Apple classification.
    
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
        Direct Apple Watch exports have device_name containing "Watch" (e.g., "Watch 7,12"
        for internal product identifiers, "Apple Watch Series 5 40mm (GPS)" for marketing names).
        
        Args:
            device_name: FIT device_info.device_name field (e.g., "iPhone", "Watch 7,12", "Apple Watch Series 5 40mm (GPS)")
            device_manufacturer_code: FIT device_info.manufacturer code (reserved for future use)
            device_product_code: FIT device_info.product code (reserved for future use)
            
        Returns:
            True if device is "iPhone" (synced via HealthKit)
            False if Apple Watch (true source workout)
            False if device_name missing/None (conservatively assume true source)
        """
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
            device_manufacturer_code: FIT device_info.manufacturer code (reserved for future use)
            device_product_code: FIT device_info.product code (reserved for future use)
            
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
            device_manufacturer_code: FIT device_info.manufacturer code (reserved for future use)
            device_product_code: FIT device_info.product code (reserved for future use)
            
        Returns:
            "apple_watch" - Native Apple Watch export (true source)
            "healthkit_synced" - Synced from another app via HealthKit (iPhone sentinel)
            "unknown" - Device not detected or missing
        """
        if device_name is None:
            return "unknown"

        device_lower = device_name.lower()

        if "iphone" in device_lower:
            return "healthkit_synced"
        if "watch" in device_lower:
            return "apple_watch"

        return "unknown"

