"""Device source classification for FIT workout ingestion.

Classifies workouts as actual device recordings vs. secondary HealthKit exports
to prevent double-counting across parallel ingestion pathways.

HealthKit-Synced Pattern (REJECTED on OneDrive):
    Apps like RunGap, Zwift, Intervals.icu sync workouts INTO HealthKit.
    HealthFit exports these with coordinated signals:
        device_name="iPhone" or app name          # Sentinel value or syncing app name
        device_model="iPhone17,1"                 # Apple internal product ID (e.g., iPhone14,2, iPhone17,1)
        manufacturer="development"                # Normal for Apple (not filtration signal)
        filename="...-Indoor Cycling-RunGap.fit"  # Source token = syncing app name
    
    Combined meaning: Secondary export. Workout exists elsewhere in primary form.
    Action: Reject during OneDrive ingestion.
    
    Detection uses dual mechanism:
        - Sentinel: device_name containing "iphone" (case-insensitive)
        - Model ID: device_model matching pattern r"iphone\\d+,\\d+" (e.g., "iPhone17,1", "iPhone14,2")
    
    Rationale: Catches both direct HealthFit exports (device_name="iPhone") AND
    third-party app syncs where device_name is app name but device_model contains
    iPhone product ID from the recording device.

Actual Device Pattern (ACCEPTED on OneDrive):
    Apple Watch records workout directly:
        device_name="Apple Watch Ultra" / "Watch 7,12"  # Contains "watch"
        device_model="Watch7,12"                         # Apple Watch model ID
        manufacturer="development"                       # Normal for all Apple
        filename="...-Indoor Cycling-AppleWatch.fit"     # Source token = device
    
    Combined meaning: Primary recording from origin device.
    Action: Accept during OneDrive ingestion.

Classification Strategy:
    - device_name AND device_model string matching (case-insensitive)
    - "iphone" in device_name OR device_model matching r"iphone\\d+,\\d+" → HealthKit-synced (reject)
    - "watch" in device_name → Apple Watch with model ID like "Watch7,12" (accept)
    - Real Apple devices have model identifiers (e.g., "iPhone17,1", "Watch8,1", "Watch7,12")
    - No manufacturer code checks (Apple uses "development" for everything)
    - FIT SDK lacks Apple product enums, so string-based classification only

Architecture Context:
    This module supports a parallel-source ingestion model with no cross-source
    deduplication. See docs/devops/BACKENDS.md#workout-ingestion-architecture
    for the complete filtration rationale and source relationship design.

Implementation:
    - FitDevice.is_healthkit_synced() → detects "iPhone" sentinel or iPhone model pattern
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
        device_model: Optional[str] = None,
        device_manufacturer_code: Optional[int] = None,
        device_product_code: Optional[int] = None,
    ) -> bool:
        """Detect if workout was synced into HealthKit from another app.
        
        HealthFit exports synced workouts with coordinated signals:
        1. Sentinel device_name="iPhone" (literal string, not actual device)
        2. OR device_model with iPhone model identifier (e.g., "iPhone17,1")
        
        This is NOT an actual iPhone recording - it indicates the workout was synced
        INTO HealthKit by another app (RunGap, Zwift, Intervals.icu, etc.).
        
        Detection strategy:
        - Check device_name for "iphone" substring (case-insensitive)
        - Check device_model for iPhone model pattern: "iPhoneNN,N" (e.g., "iPhone17,1")
        
        Direct Apple Watch exports have:
        - device_name containing "Watch" (e.g., "Watch 7,12", "Apple Watch Ultra")
        - device_model containing "Watch" (e.g., "Watch7,12")
        
        Args:
            device_name: FIT device_info.device_name field or filename-derived.
                        Sentinel "iPhone" indicates HealthKit-synced.
            device_model: FIT file_id product name. iPhone model identifiers
                         (e.g., "iPhone17,1") indicate HealthKit recording device.
            device_manufacturer_code: FIT device_info.manufacturer code (reserved for future use)
            device_product_code: FIT device_info.product code (reserved for future use)
            
        Returns:
            True if device is iPhone (synced via HealthKit)
            False if Apple Watch (true source workout)
            False if both device_name and device_model missing/None
        """
        # Check device_name for "iphone" substring
        if isinstance(device_name, str):
            device_name_lower = device_name.lower()
            if "iphone" in device_name_lower:
                return True
        
        # Check device_model for iPhone model identifier pattern (iPhoneNN,N)
        if isinstance(device_model, str):
            device_model_lower = device_model.lower()
            # Match pattern: iphone followed by digits, comma, digit(s)
            # Examples: iPhone17,1  iPhone14,2  iPhone13,4
            import re
            if re.match(r"iphone\d+,\d+", device_model_lower):
                return True
        
        return False

    @staticmethod
    def is_apple_watch_source(
        device_name: Optional[str],
        device_model: Optional[str] = None,
        device_manufacturer_code: Optional[int] = None,
        device_product_code: Optional[int] = None,
    ) -> bool:
        """Check if workout originated from Apple Watch (not synced via HealthKit).
        
        Args:
            device_name: FIT device_info.device_name field or filename-derived
            device_model: FIT file_id product name
            device_manufacturer_code: FIT device_info.manufacturer code (reserved for future use)
            device_product_code: FIT device_info.product code (reserved for future use)
            
        Returns:
            True if Apple Watch is the source
            False if HealthKit synced (iPhone sentinel or model)
        """
        if isinstance(device_name, str) and "watch" in device_name.lower():
            return True
        if isinstance(device_model, str) and "watch" in device_model.lower():
            return True
        return False

    @staticmethod
    def device_source_type(
        device_name: Optional[str],
        device_model: Optional[str] = None,
        device_manufacturer_code: Optional[int] = None,
        device_product_code: Optional[int] = None,
    ) -> str:
        """Classify device source for downstream filtering.
        
        Checks both device_name (filename-derived or FIT combined) and device_model
        (FIT file_id product) to detect HealthKit-synced workouts.
        
        Args:
            device_name: FIT device_info.device_name field or filename-derived
            device_model: FIT file_id product name (e.g., "iPhone17,1", "Watch7,12")
            device_manufacturer_code: FIT device_info.manufacturer code (reserved for future use)
            device_product_code: FIT device_info.product code (reserved for future use)
            
        Returns:
            "apple_watch" - Native Apple Watch export (true source)
            "healthkit_synced" - Synced from another app via HealthKit (iPhone sentinel or model)
            "unknown" - Device not detected or missing
        """
        # Check for HealthKit-synced first (iPhone sentinel or model identifier)
        if FitDevice.is_healthkit_synced(
            device_name=device_name,
            device_model=device_model,
            device_manufacturer_code=device_manufacturer_code,
            device_product_code=device_product_code,
        ):
            return "healthkit_synced"
        
        # Check for Apple Watch indicators
        if isinstance(device_name, str) and "watch" in device_name.lower():
            return "apple_watch"
        if isinstance(device_model, str) and "watch" in device_model.lower():
            return "apple_watch"

        return "unknown"

