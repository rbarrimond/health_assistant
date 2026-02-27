"""Tests for Apple Watch internal identifier mapping."""

import pytest

from TrainingAnalyticsPlatform.ingestion.code_mappings import (
    APPLE_WATCH_INTERNAL_IDS,
    get_apple_watch_model,
)


class TestAppleWatchInternalIds:
    """Test Apple Watch internal identifier mapping."""

    def test_watch_internal_ids_exist(self):
        """Verify APPLE_WATCH_INTERNAL_IDS dictionary is populated."""
        assert APPLE_WATCH_INTERNAL_IDS
        assert len(APPLE_WATCH_INTERNAL_IDS) > 0

    def test_ultra_3_identifier(self):
        """Verify Watch7,12 maps to Apple Watch Ultra 3."""
        assert APPLE_WATCH_INTERNAL_IDS["Watch7,12"] == "Apple Watch Ultra 3 49mm"

    def test_ultra_2_identifier(self):
        """Verify Watch7,5 maps to Apple Watch Ultra 2."""
        assert APPLE_WATCH_INTERNAL_IDS["Watch7,5"] == "Apple Watch Ultra 2 49mm"

    def test_ultra_1_identifier(self):
        """Verify Watch6,18 maps to Apple Watch Ultra."""
        assert APPLE_WATCH_INTERNAL_IDS["Watch6,18"] == "Apple Watch Ultra 49mm"

    def test_series_11_identifiers(self):
        """Verify Series 11 identifiers map correctly."""
        assert APPLE_WATCH_INTERNAL_IDS["Watch7,17"] == "Apple Watch Series 11 42mm GPS"
        assert APPLE_WATCH_INTERNAL_IDS["Watch7,18"] == "Apple Watch Series 11 46mm GPS"
        assert APPLE_WATCH_INTERNAL_IDS["Watch7,19"] == "Apple Watch Series 11 42mm GPS+Cellular"
        assert APPLE_WATCH_INTERNAL_IDS["Watch7,20"] == "Apple Watch Series 11 46mm GPS+Cellular"

    def test_se_gen1_identifiers(self):
        """Verify SE 1st gen identifiers map correctly."""
        assert APPLE_WATCH_INTERNAL_IDS["Watch5,9"] == "Apple Watch SE 40mm GPS"
        assert APPLE_WATCH_INTERNAL_IDS["Watch5,10"] == "Apple Watch SE 44mm GPS"
        assert APPLE_WATCH_INTERNAL_IDS["Watch5,11"] == "Apple Watch SE 40mm GPS+Cellular"
        assert APPLE_WATCH_INTERNAL_IDS["Watch5,12"] == "Apple Watch SE 44mm GPS+Cellular"

    def test_se_gen2_identifiers(self):
        """Verify SE 2nd gen identifiers map correctly."""
        assert APPLE_WATCH_INTERNAL_IDS["Watch6,10"] == "Apple Watch SE (2nd gen) 40mm GPS"
        assert APPLE_WATCH_INTERNAL_IDS["Watch6,11"] == "Apple Watch SE (2nd gen) 44mm GPS"

    def test_se_gen3_identifiers(self):
        """Verify SE 3rd gen identifiers map correctly."""
        assert APPLE_WATCH_INTERNAL_IDS["Watch7,13"] == "Apple Watch SE (3rd gen) 40mm GPS"
        assert APPLE_WATCH_INTERNAL_IDS["Watch7,14"] == "Apple Watch SE (3rd gen) 44mm GPS"

    def test_series_0_original_identifiers(self):
        """Verify original Apple Watch identifiers map correctly."""
        assert APPLE_WATCH_INTERNAL_IDS["Watch1,1"] == "Apple Watch (1st gen) 38mm"
        assert APPLE_WATCH_INTERNAL_IDS["Watch1,2"] == "Apple Watch (1st gen) 42mm"

    def test_get_apple_watch_model_ultra_3(self):
        """Test get_apple_watch_model() with Ultra 3 identifier."""
        result = get_apple_watch_model("Watch7,12")
        assert result == "Apple Watch Ultra 3 49mm"

    def test_get_apple_watch_model_unknown_returns_original(self):
        """Test get_apple_watch_model() returns original ID when not found."""
        result = get_apple_watch_model("Watch99,99")
        assert result == "Watch99,99"

    def test_get_apple_watch_model_series_6(self):
        """Test get_apple_watch_model() with Series 6 identifiers."""
        assert get_apple_watch_model("Watch6,1") == "Apple Watch Series 6 40mm GPS"
        assert get_apple_watch_model("Watch6,2") == "Apple Watch Series 6 44mm GPS"
        assert get_apple_watch_model("Watch6,3") == "Apple Watch Series 6 40mm GPS+Cellular"
        assert get_apple_watch_model("Watch6,4") == "Apple Watch Series 6 44mm GPS+Cellular"

    def test_coverage_all_series_represented(self):
        """Verify all major Apple Watch series are represented."""
        # Series 0-11
        for series in range(12):
            matches = [k for k in APPLE_WATCH_INTERNAL_IDS.keys() 
                      if f"Series {series}" in APPLE_WATCH_INTERNAL_IDS[k] or 
                      (series == 0 and "1st gen" in APPLE_WATCH_INTERNAL_IDS[k])]
            if series <= 11:  # Series 0-11 should exist
                assert len(matches) > 0, f"Series {series} not found in mappings"
        
        # Ultra 1-3
        ultra_models = [v for v in APPLE_WATCH_INTERNAL_IDS.values() if "Ultra" in v]
        assert len(ultra_models) >= 3, "Should have at least 3 Ultra models"
        
        # SE 1-3
        se_models = [v for v in APPLE_WATCH_INTERNAL_IDS.values() if "SE" in v]
        assert len(se_models) >= 12, "Should have at least 12 SE variants (3 gens x 4 configs)"

    def test_all_identifiers_start_with_watch(self):
        """Verify all internal IDs follow Watch#,# format."""
        for internal_id in APPLE_WATCH_INTERNAL_IDS.keys():
            assert internal_id.startswith("Watch"), f"{internal_id} doesn't start with 'Watch'"
            assert "," in internal_id, f"{internal_id} missing comma separator"
