"""Microsoft Graph OneDrive client (delegated OAuth)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)


class OneDriveGraphError(RuntimeError):
    """Raised when Microsoft Graph calls fail."""


class OneDriveGraphClient:
    """Minimal Microsoft Graph client for OneDrive Personal (delegated OAuth)."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: str,
        authorize_endpoint: str = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize",
        token_endpoint: str = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
        graph_base_url: str = "https://graph.microsoft.com/v1.0",
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.authorize_endpoint = authorize_endpoint
        self.token_endpoint = token_endpoint
        self.graph_base_url = graph_base_url

    def build_authorize_url(self, *, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "response_mode": "query",
            "scope": self.scopes,
            "state": state,
        }
        return f"{self.authorize_endpoint}?{urlencode(params)}"

    def exchange_code(self, code: str) -> Dict:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
        }
        response = requests.post(self.token_endpoint, data=data, timeout=30)
        if not response.ok:
            logger.error("Token exchange failed: %s", response.text)
            raise OneDriveGraphError("Failed to exchange authorization code.")
        return response.json()

    def refresh_access_token(self, refresh_token: str) -> Dict:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
        }
        response = requests.post(self.token_endpoint, data=data, timeout=30)
        if not response.ok:
            logger.error("Token refresh failed: %s", response.text)
            raise OneDriveGraphError("Failed to refresh access token.")
        return response.json()

    def get_drive_id(self, access_token: str) -> Optional[str]:
        url = f"{self.graph_base_url}/me/drive"
        response = requests.get(url, headers=_auth_header(access_token), timeout=30)
        if not response.ok:
            logger.warning("Failed to get drive id: %s", response.text)
            return None
        return response.json().get("id")

    def list_files(
        self,
        *,
        access_token: str,
        folder_path: str,
        modified_since: Optional[datetime],
        extensions: Optional[Iterable[str]] = None,
    ) -> list[Dict]:
        path = folder_path if folder_path.startswith("/") else f"/{folder_path}"
        url = f"{self.graph_base_url}/me/drive/root:{path}:/children"
        params = {
            "$select": "id,name,size,file,folder,lastModifiedDateTime,parentReference,eTag",
            "$top": "200",
        }
        results: list[Dict] = []
        next_url = url
        next_params = params

        while next_url:
            response = requests.get(
                next_url,
                headers=_auth_header(access_token),
                params=next_params,
                timeout=30,
            )
            if not response.ok:
                logger.error("List files failed: %s", response.text)
                raise OneDriveGraphError("Failed to list OneDrive folder.")

            data = response.json()
            items = data.get("value", [])
            for item in items:
                if "file" not in item:
                    continue
                if extensions and not _has_extension(item.get("name", ""), extensions):
                    continue
                if modified_since and not _is_newer(item, modified_since):
                    continue
                results.append(item)

            next_url = data.get("@odata.nextLink")
            next_params = None

        return results

    def download_file(self, *, access_token: str, item_id: str) -> bytes:
        url = f"{self.graph_base_url}/me/drive/items/{item_id}/content"
        response = requests.get(url, headers=_auth_header(access_token), timeout=60)
        if not response.ok:
            logger.error("Download failed: %s", response.text)
            raise OneDriveGraphError("Failed to download OneDrive file.")
        return response.content


def _auth_header(access_token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _has_extension(name: str, extensions: Iterable[str]) -> bool:
    name_lower = name.lower()
    return any(name_lower.endswith(ext) for ext in extensions)


def _is_newer(item: Dict, cutoff: datetime) -> bool:
    raw = item.get("lastModifiedDateTime")
    if not raw:
        return True
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    return ts >= cutoff.astimezone(timezone.utc)
