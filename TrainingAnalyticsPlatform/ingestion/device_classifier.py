"""Device source classification for FIT workout ingestion.

Classifies workouts as actual device recordings vs. secondary HealthKit exports
to prevent double-counting across parallel ingestion pathways.

HealthKit-Synced Pattern (REJECTED on OneDrive):
    Apps like RunGap, Zwift, Intervals.icu sync workouts INTO HealthKit.
    HealthFit exports these with coordinated signals:
        device_name="iPhone"                       # Sentinel value (not an actual device)
        manufacturer="development"                 # Normal for Apple (not filtration signal)
        filename="...-Indoor Cycling-RunGap.fit"   # Source token = syncing app name
    
    Combined meaning: Secondary export. Workout exists elsewhere in primary form.
    Action: Reject during OneDrive ingestion.

Actual Device Pattern (ACCEPTED on OneDrive):
    Apple Watch records workout directly:
        device_name="Apple Watch Ultra" / "Watch 7,12"  # Contains "watch"
        manufacturer="development"                       # Normal for all Apple
        filename="...-Indoor Cycling-AppleWatch.fit"     # Source token = device
    
    Combined meaning: Primary recording from origin device.
    Action: Accept during OneDrive ingestion.

Classification Strategy:
    - device_name string matching (case-insensitive)
    - "iphone" in device_name → HealthKit-synced sentinel (reject)
    - "watch" in device_name → Apple Watch with model ID like "Watch7,12" (accept)
    - Real Apple devices have model identifiers (e.g., "iPhone17,1", "Watch8,1", "Watch7,12")
    - No manufacturer code checks (Apple uses "development" for everything)
    - FIT SDK lacks Apple product enums, so string-based classification only

Architecture Context:
    This module supports a parallel-source ingestion model with no cross-source
    deduplication. See docs/devops/BACKENDS.md#workout-ingestion-architecture
    for the complete filtration rationale and source relationship design.

Implementation:
    - FitDevice.is_healthkit_synced() → detects "iPhone" sentinel
    - FitDevice.is_apple_watch_source() → detects "Watch" devices
    - FitDevice.device_source_type() → returns classification enum
    - Enforcement: FitIngestionBaseHandler._apply_device_source_filtration()
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
    - "healthkit_synced": HealthKit-synced via sentinel device_name="iPhone"
    - "unknown": Unclassifiable
    """

    @staticmethod
    def is_healthkit_synced(
        device_name: Optional[str],
        device_manufacturer_code: Optional[int] = None,
        device_product_code: Optional[int] = None,
    ) -> bool:
        """Detect if workout was synced into HealthKit from another app.
        
        HealthFit exports synced workouts with the literal sentinel device_name="iPhone".
        This is NOT an actual iPhone recording - it indicates the workout was synced
        INTO HealthKit by another app (RunGap, Zwift, etc.).
        Direct Apple Watch exports have device_name containing "Watch" (e.g., "Watch 7,12"
        for internal product identifiers, "Apple Watch Series 5 40mm (GPS)" for marketing names).
        
        Args:
            device_name: FIT device_info.device_name field. Sentinel "iPhone" indicates
                        HealthKit-synced. Real devices have model IDs: "iPhone17,1",
                        "Watch7,12", "Apple Watch Series 5 40mm (GPS)", etc.
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

