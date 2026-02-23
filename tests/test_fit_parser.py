"""Unit tests for fit_parser utility functions.

Note: FitParser class was removed in v13.0.0. Handlers now call create_fit_model()
directly. Model-specific tests (indoor detection, device extraction, etc.) are in
test_fit_models.py with the concrete model tests.
"""

# Allow protected member access in tests to validate internal caching behavior.
# pylint: disable=protected-access, line-too-long

from pathlib import Path

from TrainingAnalyticsPlatform.handlers.ingestion_identity import IngestionIdentityPolicy


class TestComputeFileHash:
    """Tests for compute_file_hash function."""

    def test_compute_file_hash_returns_64_char_string(self, tmp_path: Path) -> None:
        """Verify hash is 64 characters (SHA256 hex digest)."""
        test_file = tmp_path / "test.fit"
        test_file.write_bytes(b"test content")

        hash_value = IngestionIdentityPolicy.compute_file_hash(str(test_file))

        assert isinstance(hash_value, str)
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

    def test_compute_file_hash_consistency(self, tmp_path: Path) -> None:
        """Verify same file produces same hash."""
        test_file = tmp_path / "test.fit"
        content = b"identical content"
        test_file.write_bytes(content)

        hash1 = IngestionIdentityPolicy.compute_file_hash(str(test_file))
        hash2 = IngestionIdentityPolicy.compute_file_hash(str(test_file))

        assert hash1 == hash2

    def test_compute_file_hash_different_content(self, tmp_path: Path) -> None:
        """Verify different files produce different hashes."""
        file1 = tmp_path / "file1.fit"
        file2 = tmp_path / "file2.fit"
        file1.write_bytes(b"content1")
        file2.write_bytes(b"content2")

        hash1 = IngestionIdentityPolicy.compute_file_hash(str(file1))
        hash2 = IngestionIdentityPolicy.compute_file_hash(str(file2))

        assert hash1 != hash2
