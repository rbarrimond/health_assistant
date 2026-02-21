"""Utility functions for loading and processing FIT messages via fitdecode."""

import io
from pathlib import Path
from typing import Any, Dict, List

import fitdecode


def load_fit_messages(file_path_or_stream) -> tuple[List[Dict[str, Any]], str]:
    """Load FIT messages from a file or stream using fitdecode.

    Handles file paths (str/Path), in-memory bytes, and file streams.
    Returns parsed messages and source description for error reporting.

    Args:
        file_path_or_stream: Path to FIT file, bytes/bytearray, or file-like stream

    Returns:
        Tuple of (messages list, source description for errors)

    Raises:
        RuntimeError: If FIT file parsing fails
        Exception: If stream handling fails
    """
    stream = None
    should_close = False
    source_desc = "unknown"

    try:
        if isinstance(file_path_or_stream, (bytes, bytearray)):
            stream = io.BytesIO(file_path_or_stream)
            source_desc = "bytes stream"
        elif isinstance(file_path_or_stream, (str, Path)):
            stream = open(file_path_or_stream, "rb")
            should_close = True
            source_desc = f"file {file_path_or_stream}"
        else:
            stream = file_path_or_stream
            source_desc = "file stream"

        messages: List[Dict[str, Any]] = []
        try:
            with fitdecode.FitReader(stream, processor=fitdecode.DefaultDataProcessor()) as reader:
                for frame in reader:
                    if not isinstance(frame, fitdecode.FitDataMessage):
                        continue
                    messages.append({
                        "name": frame.name,
                        "frame": frame,
                        "fields": {field.name: field for field in frame.fields},
                    })
        except Exception as exc:
            raise RuntimeError(
                f"FIT file parsing failed: {exc.__class__.__name__}: {exc}"
            ) from exc
        finally:
            if should_close and stream is not None:
                stream.close()

        return messages, source_desc
    except Exception:
        if should_close and stream is not None:
            stream.close()
        raise
