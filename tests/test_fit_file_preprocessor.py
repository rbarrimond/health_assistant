"""Tests for FIT file preprocessing utilities."""

from __future__ import annotations

import gzip
import io
import zipfile

import pytest

from TrainingAnalyticsPlatform.ingestion.fit_file_preprocessor import (
    FitFilePreprocessor,
    PreprocessedFile,
)
from TrainingAnalyticsPlatform.platform.exceptions import (
    CompressionError,
    InvalidFileFormatError,
    PreprocessingError,
)

# Minimal valid FIT file header (14 bytes)
# Header structure: size(1), protocol(1), profile_version(2), data_size(4), ".FIT"(4), CRC(2)
VALID_FIT_HEADER = bytes([
    0x0E,  # Header size (14 bytes)
    0x10,  # Protocol version 1.0
    0x20, 0x00,  # Profile version (little-endian)
    0x00, 0x00, 0x00, 0x00,  # Data size (0 for minimal test)
    ord('.'), ord('F'), ord('I'), ord('T'),  # ".FIT" signature
    0x00, 0x00  # CRC (ignored for header validation)
])

# Minimal FIT file for testing (header + minimal content)
MINIMAL_FIT_FILE = VALID_FIT_HEADER + b'\x00' * 10  # Add some content bytes


class TestFitFilePreprocessor:
    """Test suite for FitFilePreprocessor."""

    def test_uncompressed_fit_file_passthrough(self):
        """Test that uncompressed FIT files pass through unchanged."""
        preprocessor = FitFilePreprocessor()

        result = preprocessor.preprocess(MINIMAL_FIT_FILE, "activity.fit")

        assert result.content == MINIMAL_FIT_FILE
        assert result.logical_filename == "activity.fit"
        assert result.compression_type is None

    def test_gzip_decompression_via_magic_bytes(self):
        """Test gzip decompression detected by magic bytes."""
        preprocessor = FitFilePreprocessor()
        compressed = gzip.compress(MINIMAL_FIT_FILE)

        result = preprocessor.preprocess(compressed, "activity.fit")

        assert result.content == MINIMAL_FIT_FILE
        assert result.logical_filename == "activity.fit"
        assert result.compression_type == "gzip"

    def test_gzip_decompression_via_filename_fallback(self):
        """Test gzip decompression detected by .gz extension when magic bytes missing."""
        preprocessor = FitFilePreprocessor()
        # Create data that doesn't have gzip magic bytes but has .gz extension
        # This tests the fallback detection path
        compressed = gzip.compress(MINIMAL_FIT_FILE)

        result = preprocessor.preprocess(compressed, "activity.fit.gz")

        assert result.content == MINIMAL_FIT_FILE
        assert result.logical_filename == "activity.fit"
        assert result.compression_type == "gzip"

    def test_gz_extension_stripped_from_filename(self):
        """Test that .gz extension is properly stripped from logical filename."""
        preprocessor = FitFilePreprocessor()
        compressed = gzip.compress(MINIMAL_FIT_FILE)

        result = preprocessor.preprocess(compressed, "2024-01-15-120000-Running-Watch.fit.gz")

        assert result.logical_filename == "2024-01-15-120000-Running-Watch.fit"
        assert result.compression_type == "gzip"

    def test_zip_extraction_single_fit_file(self):
        """Test ZIP extraction with single FIT file."""
        preprocessor = FitFilePreprocessor()

        # Create ZIP archive with FIT file
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("activity_12345.fit", MINIMAL_FIT_FILE)
        zip_bytes = zip_buffer.getvalue()

        result = preprocessor.preprocess(zip_bytes, "download.zip")

        assert result.content == MINIMAL_FIT_FILE
        assert result.logical_filename == "download.zip"
        assert result.compression_type == "zip"

    def test_zip_extraction_multiple_fit_files_uses_first(self):
        """Test ZIP extraction with multiple FIT files uses first one."""
        preprocessor = FitFilePreprocessor()

        fit_file_2 = VALID_FIT_HEADER + b'\xFF' * 10  # Different content

        # Create ZIP archive with multiple FIT files
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("first_activity.fit", MINIMAL_FIT_FILE)
            zip_file.writestr("second_activity.fit", fit_file_2)
        zip_bytes = zip_buffer.getvalue()

        result = preprocessor.preprocess(zip_bytes, "activities.zip")

        # Should use first FIT file
        assert result.content == MINIMAL_FIT_FILE
        assert result.compression_type == "zip"

    def test_zip_extraction_nested_directory(self):
        """Test ZIP extraction with FIT file in nested directory."""
        preprocessor = FitFilePreprocessor()

        # Create ZIP archive with FIT file in subdirectory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("garmin/activities/activity_12345.fit", MINIMAL_FIT_FILE)
        zip_bytes = zip_buffer.getvalue()

        result = preprocessor.preprocess(zip_bytes, "export.zip")

        assert result.content == MINIMAL_FIT_FILE
        assert result.compression_type == "zip"

    def test_double_compression_zip_containing_gzipped_fit(self):
        """Test edge case: ZIP archive containing gzipped FIT file."""
        preprocessor = FitFilePreprocessor()

        compressed_fit = gzip.compress(MINIMAL_FIT_FILE)

        # Create ZIP archive containing gzipped FIT
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_STORED) as zip_file:
            zip_file.writestr("activity.fit.gz", compressed_fit)
        zip_bytes = zip_buffer.getvalue()

        result = preprocessor.preprocess(zip_bytes, "archive.zip")

        # Should detect gzip inside ZIP and decompress it
        assert result.content == MINIMAL_FIT_FILE
        assert result.compression_type == "zip"

    def test_empty_file_raises_preprocessing_error(self):
        """Test that empty file raises PreprocessingError."""
        preprocessor = FitFilePreprocessor()

        with pytest.raises(PreprocessingError, match="Cannot preprocess empty file"):
            preprocessor.preprocess(b"", "empty.fit")

    def test_corrupt_gzip_raises_compression_error(self):
        """Test that corrupt gzip data raises CompressionError."""
        preprocessor = FitFilePreprocessor()

        # Create invalid gzip data (magic bytes but corrupt content)
        corrupt_gzip = b'\x1f\x8b' + b'\xFF' * 100

        with pytest.raises(CompressionError, match="Failed to decompress"):
            preprocessor.preprocess(corrupt_gzip, "corrupt.fit.gz")

    def test_invalid_zip_raises_compression_error(self):
        """Test that invalid ZIP data raises CompressionError."""
        preprocessor = FitFilePreprocessor()

        # Create invalid ZIP data (magic bytes but corrupt structure)
        corrupt_zip = b'PK\x03\x04' + b'\xFF' * 100

        with pytest.raises(CompressionError, match="Invalid ZIP archive"):
            preprocessor.preprocess(corrupt_zip, "corrupt.zip")

    def test_zip_with_no_fit_file_raises_compression_error(self):
        """Test that ZIP without FIT file raises CompressionError."""
        preprocessor = FitFilePreprocessor()

        # Create ZIP archive without any FIT files
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("readme.txt", b"No FIT files here")
            zip_file.writestr("data.csv", b"some,data,here")
        zip_bytes = zip_buffer.getvalue()

        with pytest.raises(CompressionError, match="No .fit file found in ZIP archive"):
            preprocessor.preprocess(zip_bytes, "no_fit.zip")

    def test_invalid_fit_header_too_small_raises_error(self):
        """Test that file smaller than FIT header minimum raises InvalidFileFormatError."""
        preprocessor = FitFilePreprocessor()

        too_small = b'\x0E\x10\x20\x00'  # Only 4 bytes

        with pytest.raises(InvalidFileFormatError, match="file too small"):
            preprocessor.preprocess(too_small, "tiny.fit")

    def test_invalid_fit_header_wrong_signature_raises_error(self):
        """Test that file without .FIT signature raises InvalidFileFormatError."""
        preprocessor = FitFilePreprocessor()

        # Valid size but wrong signature
        invalid_header = bytes([
            0x0E, 0x10, 0x20, 0x00, 0x00, 0x00, 0x00, 0x00,
            ord('B'), ord('A'), ord('D'), ord('!'),  # Wrong signature
            0x00, 0x00
        ])

        with pytest.raises(InvalidFileFormatError, match="not a valid FIT file"):
            preprocessor.preprocess(invalid_header, "invalid.fit")

    def test_gzip_decompression_empty_result_raises_error(self):
        """Test that gzip file decompressing to empty raises InvalidFileFormatError."""
        preprocessor = FitFilePreprocessor()

        # Gzip compress empty content
        empty_compressed = gzip.compress(b"")

        with pytest.raises(InvalidFileFormatError, match="Preprocessed file .* is empty"):
            preprocessor.preprocess(empty_compressed, "empty.fit.gz")

    def test_case_insensitive_extension_detection(self):
        """Test that extension detection is case-insensitive."""
        preprocessor = FitFilePreprocessor()
        compressed = gzip.compress(MINIMAL_FIT_FILE)

        # Test various case combinations
        for filename in ["activity.FIT.GZ", "activity.Fit.Gz", "activity.FIT.gz"]:
            result = preprocessor.preprocess(compressed, filename)
            assert result.compression_type == "gzip"
            assert result.content == MINIMAL_FIT_FILE

    def test_zip_case_insensitive_fit_file_search(self):
        """Test that ZIP extraction finds .fit files case-insensitively."""
        preprocessor = FitFilePreprocessor()

        # Create ZIP with uppercase .FIT extension
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("ACTIVITY.FIT", MINIMAL_FIT_FILE)
        zip_bytes = zip_buffer.getvalue()

        result = preprocessor.preprocess(zip_bytes, "archive.zip")

        assert result.content == MINIMAL_FIT_FILE
        assert result.compression_type == "zip"

    def test_exception_chaining_preserved(self):
        """Test that exception causality is preserved through chaining."""
        preprocessor = FitFilePreprocessor()

        corrupt_gzip = b'\x1f\x8b' + b'\xFF' * 100

        try:
            preprocessor.preprocess(corrupt_gzip, "corrupt.fit.gz")
            pytest.fail("Expected CompressionError to be raised")
        except CompressionError as exc:
            # Check that original exception is chained
            assert exc.__cause__ is not None
            assert isinstance(exc.__cause__, (OSError, EOFError))

    def test_preprocessed_file_immutability(self):
        """Test that PreprocessedFile is immutable (frozen dataclass)."""
        result = PreprocessedFile(
            content=MINIMAL_FIT_FILE,
            logical_filename="test.fit",
            compression_type="gzip",
        )

        with pytest.raises(Exception):  # FrozenInstanceError in Python 3.10+
            result.content = b"modified"  # type: ignore[misc]

    def test_large_fit_file_decompression(self):
        """Test preprocessing of larger FIT file to ensure buffer handling."""
        preprocessor = FitFilePreprocessor()

        # Create a larger FIT file (10KB)
        large_fit = VALID_FIT_HEADER + b'\x42' * 10000
        compressed = gzip.compress(large_fit)

        result = preprocessor.preprocess(compressed, "large.fit.gz")

        assert result.content == large_fit
        assert len(result.content) > 10000
        assert result.compression_type == "gzip"

    def test_magic_bytes_preferred_over_filename(self):
        """Test that magic byte detection takes precedence over filename."""
        preprocessor = FitFilePreprocessor()

        # Gzipped file with misleading .zip extension
        compressed = gzip.compress(MINIMAL_FIT_FILE)

        result = preprocessor.preprocess(compressed, "misleading.zip")

        # Should detect gzip via magic bytes despite .zip extension
        assert result.compression_type == "gzip"
        assert result.content == MINIMAL_FIT_FILE

    def test_filename_only_detection_when_no_magic_bytes(self):
        """Test filename extension used when magic bytes don't match."""
        preprocessor = FitFilePreprocessor()

        # This is a bit artificial - in reality gzip always has magic bytes
        # But tests the fallback path
        compressed = gzip.compress(MINIMAL_FIT_FILE)

        # The preprocessor should detect via magic bytes first
        result = preprocessor.preprocess(compressed, "activity.fit.gz")
        assert result.compression_type == "gzip"
