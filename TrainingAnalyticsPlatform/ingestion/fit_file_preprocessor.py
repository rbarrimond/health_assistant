"""FIT file preprocessing utilities for handling compression and validation.

This module provides utilities to preprocess FIT files before parsing,
handling transport encoding concerns (gzip, ZIP) that should not leak
into domain models or handler orchestration logic.
"""

from __future__ import annotations

import gzip
import io
import logging
import zipfile
from dataclasses import dataclass
from typing import Optional

from TrainingAnalyticsPlatform.platform.exceptions import (
    CompressionError,
    InvalidFileFormatError,
    PreprocessingError,
)

logger = logging.getLogger(__name__)

# Magic bytes for compression format detection
GZIP_MAGIC = b'\x1f\x8b'
ZIP_MAGIC = b'PK\x03\x04'  # Standard ZIP file signature
FIT_FILE_SIGNATURE = b'.FIT'  # FIT file header signature (bytes 8-11)
FIT_MIN_HEADER_SIZE = 14  # Minimum FIT file header size


@dataclass(frozen=True)
class PreprocessedFile:
    """Result of file preprocessing operations.
    
    Attributes:
        content: Decompressed FIT file bytes ready for parsing
        logical_filename: Filename with compression extensions stripped
        compression_type: Detected compression type ('gzip', 'zip', or None)
    """
    
    content: bytes
    logical_filename: str
    compression_type: Optional[str]


class FitFilePreprocessor:
    """Handles decompression and validation of FIT files from various sources.
    
    This class centralizes all transport encoding concerns (gzip, ZIP)
    to maintain separation between transport/storage layers and domain logic.
    
    Usage:
        preprocessor = FitFilePreprocessor()
        result = preprocessor.preprocess(raw_bytes, "activity.fit.gz")
        # result.content contains decompressed FIT bytes
        # result.logical_filename is "activity.fit"
        # result.compression_type is "gzip"
    """
    
    def preprocess(self, raw_bytes: bytes, filename: str) -> PreprocessedFile:
        """Preprocess raw file bytes into ready-to-parse FIT data.
        
        Handles:
        - Compression detection (magic bytes + filename fallback)
        - Gzip decompression
        - ZIP extraction (finds .fit file in archive)
        - FIT header validation
        
        Args:
            raw_bytes: Raw file bytes as downloaded/read from source
            filename: Original filename (used for detection fallback)
            
        Returns:
            PreprocessedFile with decompressed content and metadata
            
        Raises:
            CompressionError: If decompression/extraction fails
            InvalidFileFormatError: If result is not a valid FIT file
            PreprocessingError: For other preprocessing failures
        """
        if not raw_bytes:
            raise PreprocessingError(f"Cannot preprocess empty file: {filename}")
        
        # Detect compression format
        compression_type = self._detect_compression(raw_bytes, filename)
        
        # Decompress/extract based on detected format
        if compression_type == 'gzip':
            content = self._decompress_gzip(raw_bytes, filename)
            logical_filename = self._strip_gz_extension(filename)
        elif compression_type == 'zip':
            content = self._extract_from_zip(raw_bytes, filename)
            logical_filename = filename  # ZIP may contain differently named FIT
        else:
            # No compression detected - use raw bytes
            content = raw_bytes
            logical_filename = filename
        
        # Validate that we have a valid FIT file
        self._validate_fit_header(content, logical_filename)
        
        logger.info(
            "Preprocessed %s: %s → %d bytes FIT data",
            filename,
            compression_type or "uncompressed",
            len(content),
        )
        
        return PreprocessedFile(
            content=content,
            logical_filename=logical_filename,
            compression_type=compression_type,
        )
    
    def _detect_compression(self, raw_bytes: bytes, filename: str) -> Optional[str]:
        """Detect compression format using magic bytes with filename fallback.
        
        Args:
            raw_bytes: Raw file bytes to inspect
            filename: Filename to use for fallback detection
            
        Returns:
            'gzip', 'zip', or None if no compression detected
        """
        # Check magic bytes first (reliable)
        if raw_bytes[:2] == GZIP_MAGIC:
            logger.debug("Detected gzip compression via magic bytes (0x1f8b)")
            return 'gzip'
        
        if raw_bytes[:4] == ZIP_MAGIC:
            logger.debug("Detected ZIP compression via magic bytes (PK)")
            return 'zip'
        
        # Fallback to filename extension (less reliable but handles edge cases)
        filename_lower = filename.lower()
        if filename_lower.endswith('.gz'):
            logger.debug(
                "Detected gzip compression via filename extension (magic bytes not found)"
            )
            return 'gzip'
        
        if filename_lower.endswith('.zip'):
            logger.debug(
                "Detected ZIP compression via filename extension (magic bytes not found)"
            )
            return 'zip'
        
        logger.debug("No compression detected")
        return None
    
    def _decompress_gzip(self, gzip_data: bytes, filename: str) -> bytes:
        """Decompress gzipped FIT file.
        
        Args:
            gzip_data: Gzipped file bytes
            filename: Original filename (for error messages)
            
        Returns:
            Decompressed FIT file bytes
            
        Raises:
            CompressionError: If decompression fails
        """
        compressed_size = len(gzip_data)
        logger.debug(
            "Decompressing gzipped file %s (%d compressed bytes)",
            filename,
            compressed_size,
        )
        
        try:
            fit_data = gzip.decompress(gzip_data)
            decompressed_size = len(fit_data)
            compression_ratio = (
                compressed_size / decompressed_size if decompressed_size > 0 else 0
            )
            logger.debug(
                "Successfully decompressed to %d bytes (%.1fx compression ratio)",
                decompressed_size,
                compression_ratio,
            )
            return fit_data
        except (OSError, EOFError) as exc:
            # OSError catches BadGzipFile and other gzip errors
            # EOFError catches truncated files
            raise CompressionError(
                f"Failed to decompress gzipped file {filename}: {exc}"
            ) from exc
    
    def _extract_from_zip(self, zip_data: bytes, filename: str) -> bytes:
        """Extract FIT file from ZIP archive.
        
        Args:
            zip_data: ZIP file bytes
            filename: Original filename (for error messages)
            
        Returns:
            Extracted FIT file bytes
            
        Raises:
            CompressionError: If extraction fails or ZIP is invalid
        """
        logger.debug(
            "Attempting ZIP extraction for %s (%d bytes)",
            filename,
            len(zip_data),
        )
        
        try:
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_file:
                # Find .fit or .fit.gz files in the archive
                fit_files = [
                    name for name in zip_file.namelist()
                    if name.lower().endswith('.fit') or name.lower().endswith('.fit.gz')
                ]
                
                if not fit_files:
                    raise CompressionError(
                        f"No .fit file found in ZIP archive {filename}. "
                        f"Archive contains: {', '.join(zip_file.namelist())}"
                    )
                
                if len(fit_files) > 1:
                    logger.warning(
                        "Multiple FIT files in archive %s: %s. Using first file.",
                        filename,
                        fit_files,
                    )
                
                fit_filename = fit_files[0]
                fit_data = zip_file.read(fit_filename)
                
                logger.debug(
                    "Successfully extracted %s from ZIP archive (%d bytes)",
                    fit_filename,
                    len(fit_data),
                )
                
                # Check if extracted content is itself gzipped (double compression)
                if fit_data[:2] == GZIP_MAGIC:
                    logger.info(
                        "Detected gzipped FIT file inside ZIP archive, decompressing"
                    )
                    fit_data = self._decompress_gzip(fit_data, fit_filename)
                
                return fit_data
                
        except zipfile.BadZipFile as zip_exc:
            # ZIP extraction failed - might be corrupted or mislabeled
            raise CompressionError(
                f"Invalid ZIP archive {filename}: {zip_exc}. "
                "File may be corrupted or mislabeled."
            ) from zip_exc
    
    def _validate_fit_header(self, fit_data: bytes, filename: str) -> None:
        """Validate FIT file header format.
        
        Args:
            fit_data: FIT file bytes to validate
            filename: Logical filename (for error messages)
            
        Raises:
            InvalidFileFormatError: If validation fails
        """
        if not fit_data:
            raise InvalidFileFormatError(
                f"Preprocessed file {filename} is empty"
            )
        
        # FIT files have a 14-byte header minimum
        if len(fit_data) < FIT_MIN_HEADER_SIZE:
            raise InvalidFileFormatError(
                f"Invalid FIT file {filename}: "
                f"file too small ({len(fit_data)} bytes, minimum {FIT_MIN_HEADER_SIZE} bytes required)"
            )
        
        # Check for FIT file signature ".FIT" at bytes 8-11
        if fit_data[8:12] != FIT_FILE_SIGNATURE:
            header_hex = fit_data[:16].hex() if len(fit_data) >= 16 else fit_data.hex()
            raise InvalidFileFormatError(
                f"File {filename} is not a valid FIT file. "
                f"Expected '.FIT' signature at offset 8-11, but got {fit_data[8:12]!r}. "
                f"First bytes (hex): {header_hex}"
            )
        
        logger.debug("FIT header validation passed for %s", filename)
    
    def _strip_gz_extension(self, filename: str) -> str:
        """Remove .gz extension from filename.
        
        Args:
            filename: Original filename
            
        Returns:
            Filename with .gz extension removed if present
        """
        if filename.lower().endswith('.gz'):
            return filename[:-3]
        return filename
