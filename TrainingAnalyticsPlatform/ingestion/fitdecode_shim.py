"""Compatibility shim that exposes a fitparse-like API over fitdecode."""

from __future__ import annotations

import importlib
import io
from pathlib import Path
from typing import Any, Iterable, List, Optional


class FitField:
    """Simple field wrapper matching fitparse attributes."""

    def __init__(
        self,
        name: str,
        value=None,
        raw_value=None,
        units: Optional[str] = None,
    ):
        self.name = name
        self.value = value
        self.raw_value = raw_value
        self.units = units


class FitMessage:
    """Simple message wrapper matching fitparse access patterns."""

    def __init__(
        self,
        name: str,
        fields: List[FitField],
        developer_fields: List[FitField],
    ):
        self.name = name
        self.fields = fields
        self.developer_fields = developer_fields

    def get(self, field_name: str):
        """Get the value of a field by name, searching both standard and developer fields."""
        for field in self.fields:
            if field.name == field_name:
                return field
        return None


class FitFile:
    """Fitdecode-backed reader with a fitparse-like API."""

    def __init__(self, file_path_or_stream):
        self._messages: List[FitMessage] = []
        self._load_messages(file_path_or_stream)

    def _load_messages(self, file_path_or_stream) -> None:
        """Read FIT messages via fitdecode and cache them."""
        try:
            fitdecode = importlib.import_module("fitdecode")
            fit_reader_cls = fitdecode.FitReader
            data_processor_cls = fitdecode.DefaultDataProcessor
            data_message_cls = fitdecode.FitDataMessage
        except ImportError as exc:  # pragma: no cover - environment dependency
            raise ImportError(
                "fitdecode is required for FIT parsing. Install it in the runtime."
            ) from exc
        except AttributeError as exc:  # pragma: no cover - version mismatch
            raise RuntimeError(
                "Incompatible fitdecode version. Ensure fitdecode>=0.10.0 is installed."
            ) from exc

        should_close = False
        if isinstance(file_path_or_stream, (bytes, bytearray)):
            stream = io.BytesIO(file_path_or_stream)
        elif isinstance(file_path_or_stream, (str, Path)):
            stream = open(file_path_or_stream, "rb")
            should_close = True
        else:
            stream = file_path_or_stream

        try:
            with fit_reader_cls(stream, processor=data_processor_cls()) as reader:
                for frame in reader:
                    if not isinstance(frame, data_message_cls):
                        continue
                    name = getattr(frame, "name", None) or frame.__class__.__name__
                    fields, dev_fields = self._convert_fields(frame)
                    self._messages.append(FitMessage(name, fields, dev_fields))
        except Exception as exc:
            # Re-raise with context about what failed
            raise RuntimeError(
                f"FIT file parsing failed via fitdecode: {exc.__class__.__name__}: {exc}"
            ) from exc
        finally:
            if should_close:
                stream.close()

    @staticmethod
    def _convert_fields(
        message: Any,
    ) -> tuple[List[FitField], List[FitField]]:
        """Convert fitdecode fields into fitparse-like field objects."""
        fields: List[FitField] = []
        dev_fields: List[FitField] = []
        for field in getattr(message, "fields", []):
            fields.append(
                FitField(
                    name=getattr(field, "name", ""),
                    value=getattr(field, "value", None),
                    raw_value=getattr(field, "raw_value", None),
                    units=getattr(field, "units", None),
                )
            )
        for field in getattr(message, "developer_fields", []):
            dev_fields.append(
                FitField(
                    name=getattr(field, "name", ""),
                    value=getattr(field, "value", None),
                    raw_value=getattr(field, "raw_value", None),
                    units=getattr(field, "units", None),
                )
            )
        return fields, dev_fields

    def get_messages(self, name: Optional[str] = None) -> Iterable[FitMessage]:
        """Get messages by name, or all messages if name is None."""
        if name is None:
            return list(self._messages)
        return [msg for msg in self._messages if msg.name == name]
