"""iCloud Drive WebDAV client for listing and downloading files."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Iterable, List, Optional, Set
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ICloudWebDAVError(RuntimeError):
    """Raised when iCloud WebDAV calls fail."""


class ICloudFile(BaseModel):
    """File metadata from iCloud WebDAV listing."""
    name: str
    path: str
    modified_at: Optional[datetime]
    size_bytes: Optional[int]


class ICloudWebDAVClient:
    """Minimal WebDAV client for iCloud Drive."""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password)
        self.session = requests.Session()

    def _build_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    def list_files(
        self,
        folder_path: str,
        modified_since: Optional[datetime] = None,
        extensions: Optional[Set[str]] = None,
    ) -> List[Dict]:
        """List files within a folder using WebDAV PROPFIND."""
        url = self._build_url(folder_path)
        headers = {"Depth": "1"}
        body = """<?xml version="1.0" encoding="utf-8" ?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:displayname />
    <d:getlastmodified />
    <d:getcontentlength />
  </d:prop>
</d:propfind>"""

        response = self.session.request(
            "PROPFIND",
            url,
            headers=headers,
            data=body,
            auth=self.auth,
            timeout=30,
        )
        if response.status_code not in (207, 200):
            raise ICloudWebDAVError(
                f"WebDAV PROPFIND failed: {response.status_code} {response.text}"
            )

        files = []
        for file_info in _parse_multistatus(response.text):
            # Skip directories
            if file_info.path.endswith("/"):
                continue

            if extensions and not _has_extension(file_info.name, extensions):
                continue

            if modified_since and file_info.modified_at:
                if file_info.modified_at < modified_since:
                    continue

            files.append({
                "name": file_info.name,
                "path": file_info.path,
                "modified_at": file_info.modified_at.isoformat() if file_info.modified_at else None,
                "size_bytes": file_info.size_bytes,
            })

        return files

    def download_file(self, path: str) -> bytes:
        """Download a file by WebDAV path."""
        url = self._build_url(path)
        response = self.session.get(url, auth=self.auth, timeout=60)
        if response.status_code != 200:
            raise ICloudWebDAVError(
                f"WebDAV GET failed: {response.status_code} {response.text}"
            )
        return response.content


def _parse_multistatus(xml_text: str) -> Iterable[ICloudFile]:
    """Parse WebDAV multistatus response into file entries."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ICloudWebDAVError(f"Failed to parse WebDAV XML: {exc}") from exc

    ns = {"d": "DAV:"}
    for response in root.findall("d:response", ns):
        href = response.findtext("d:href", default="", namespaces=ns)
        href = unquote(href)
        parsed = urlparse(href)
        path = parsed.path if parsed.path else href

        prop = response.find("d:propstat/d:prop", ns)
        if prop is None:
            continue

        name = prop.findtext("d:displayname", default="", namespaces=ns)
        last_modified = prop.findtext("d:getlastmodified", default=None, namespaces=ns)
        size_text = prop.findtext("d:getcontentlength", default=None, namespaces=ns)

        modified_at = _parse_http_date(last_modified) if last_modified else None
        size_bytes = int(size_text) if size_text and size_text.isdigit() else None

        if not name:
            name = path.rstrip("/").split("/")[-1]

        yield ICloudFile(name=name, path=path, modified_at=modified_at, size_bytes=size_bytes)


def _parse_http_date(value: str) -> Optional[datetime]:
    """Parse RFC 1123 date strings to timezone-aware UTC datetime."""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _has_extension(name: str, extensions: Set[str]) -> bool:
    lower = name.lower()
    return any(lower.endswith(ext) for ext in extensions)
