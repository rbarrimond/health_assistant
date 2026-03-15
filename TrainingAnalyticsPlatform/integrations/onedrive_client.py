"""Microsoft Graph OneDrive client (delegated OAuth)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional
from urllib.parse import urlencode

import requests

from TrainingAnalyticsPlatform.platform.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


class OneDriveGraphError(ExternalServiceError):
    """Raised when Microsoft Graph calls fail."""


class OneDriveDeltaTokenExpiredError(OneDriveGraphError):
    """Raised when a stored OneDrive delta token is no longer valid."""


class OneDriveGraphClient:
    """Minimal Microsoft Graph client for OneDrive Personal (delegated OAuth)."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: str,
        authorize_endpoint: str = (
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
        ),
        token_endpoint: str = (
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
        ),
        graph_base_url: str = "https://graph.microsoft.com/v1.0",
    ) -> None:
        """Initialize the client with OAuth and Graph endpoints."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.authorize_endpoint = authorize_endpoint
        self.token_endpoint = token_endpoint
        self.graph_base_url = graph_base_url

    def build_authorize_url(self, *, state: str) -> str:
        """Build a Microsoft login URL for delegated OAuth."""
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
        """Exchange an authorization code for access and refresh tokens."""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
        }
        try:
            response = requests.post(self.token_endpoint, data=data, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.error("Token exchange failed: %s", exc)
            raise OneDriveGraphError("Failed to exchange authorization code") from exc
        except ValueError as exc:
            logger.error("Token exchange returned invalid JSON")
            raise OneDriveGraphError("Token exchange returned invalid response payload") from exc

    def refresh_access_token(self, refresh_token: str) -> Dict:
        """Refresh the access token using a refresh token."""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
        }
        try:
            response = requests.post(self.token_endpoint, data=data, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.error("Token refresh failed: %s", exc)
            raise OneDriveGraphError("Failed to refresh access token") from exc
        except ValueError as exc:
            logger.error("Token refresh returned invalid JSON")
            raise OneDriveGraphError("Token refresh returned invalid response payload") from exc

    def get_drive_id(self, access_token: str) -> Optional[str]:
        """Return the user's drive id, if available."""
        url = f"{self.graph_base_url}/me/drive"
        try:
            response = requests.get(url, headers=_auth_header(access_token), timeout=30)
            response.raise_for_status()
            return response.json().get("id")
        except requests.RequestException as exc:
            logger.warning("Failed to get drive id: %s", exc)
            return None
        except ValueError as exc:
            logger.warning("Drive id response returned invalid JSON: %s", exc)
            return None

    def list_files(
        self,
        *,
        access_token: str,
        folder_path: str,
        modified_since: Optional[datetime],
        extensions: Optional[Iterable[str]] = None,
    ) -> list[Dict]:
        """List files in a OneDrive folder with optional filters."""
        path = _normalize_folder_path(folder_path)
        url = f"{self.graph_base_url}/me/drive/root:{path}:/children"
        params = {
            "$select": "id,name,size,file,folder,lastModifiedDateTime,parentReference,eTag,cTag",
            "$top": "200",
        }
        results: list[Dict] = []

        for item in _iter_drive_items(access_token, url, params):
            if _should_include(item, extensions, modified_since):
                results.append(item)

        return results

    def list_files_delta(
        self,
        *,
        access_token: str,
        folder_path: str,
        delta_link: Optional[str] = None,
        extensions: Optional[Iterable[str]] = None,
    ) -> tuple[list[Dict], Optional[str]]:
        """List changed files using OneDrive delta query and return next delta link."""
        path = _normalize_folder_path(folder_path)
        url = delta_link or f"{self.graph_base_url}/me/drive/root:{path}:/delta"
        params = None if delta_link else {
            "$select": "id,name,size,file,folder,lastModifiedDateTime,parentReference,eTag,cTag,deleted",
            "$top": "200",
        }
        results: list[Dict] = []
        latest_delta_link: Optional[str] = None

        next_url = url
        next_params: Optional[Dict[str, str]] = params

        while next_url:
            data = self._fetch_delta_page(
                access_token=access_token,
                url=next_url,
                params=next_params,
            )

            for item in data.get("value", []):
                if _should_include(item, extensions, modified_since=None):
                    results.append(item)

            latest_delta_link = data.get("@odata.deltaLink") or latest_delta_link
            next_url = data.get("@odata.nextLink")
            next_params = None

        return results, latest_delta_link

    def _fetch_delta_page(
        self,
        *,
        access_token: str,
        url: str,
        params: Optional[Dict[str, str]],
    ) -> Dict:
        """Fetch one page of OneDrive delta response."""
        try:
            response = requests.get(
                url,
                headers=_auth_header(access_token),
                params=params,
                timeout=30,
            )
            if response.status_code == 410:
                raise OneDriveDeltaTokenExpiredError(
                    "OneDrive delta token expired; full resync required"
                )
            response.raise_for_status()
            return response.json()
        except OneDriveDeltaTokenExpiredError:
            raise
        except requests.RequestException as exc:
            logger.error("Delta list files failed: %s", exc)
            raise OneDriveGraphError("Failed to list OneDrive delta changes") from exc
        except ValueError as exc:
            logger.error("Delta list files returned invalid JSON")
            raise OneDriveGraphError("Invalid OneDrive delta response payload") from exc

    def download_file(self, *, access_token: str, item_id: str) -> bytes:
        """Download a OneDrive file by item id."""
        url = f"{self.graph_base_url}/me/drive/items/{item_id}/content"
        try:
            response = requests.get(url, headers=_auth_header(access_token), timeout=60)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            logger.error("Download failed: %s", exc)
            raise OneDriveGraphError("Failed to download OneDrive file") from exc


def _auth_header(access_token: str) -> Dict[str, str]:
    """Return the authorization header for Graph requests."""
    return {"Authorization": f"Bearer {access_token}"}


def _normalize_folder_path(folder_path: str) -> str:
    """Ensure the folder path starts with a leading slash."""
    return folder_path if folder_path.startswith("/") else f"/{folder_path}"


def _iter_drive_items(
    access_token: str,
    url: str,
    params: Dict[str, str],
) -> Iterable[Dict]:
    """Yield items from paginated Graph responses."""
    next_url = url
    next_params: Optional[Dict[str, str]] = params

    while next_url:
        try:
            response = requests.get(
                next_url,
                headers=_auth_header(access_token),
                params=next_params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.error("List files failed: %s", exc)
            raise OneDriveGraphError("Failed to list OneDrive folder") from exc
        except ValueError as exc:
            logger.error("List files returned invalid JSON")
            raise OneDriveGraphError("Invalid OneDrive list response payload") from exc

        for item in data.get("value", []):
            yield item

        next_url = data.get("@odata.nextLink")
        next_params = None


def _should_include(
    item: Dict,
    extensions: Optional[Iterable[str]],
    modified_since: Optional[datetime],
) -> bool:
    """Return True if the item passes the file filters."""
    if "file" not in item:
        return False
    if extensions and not _has_extension(item.get("name", ""), extensions):
        return False
    if modified_since and not _is_newer(item, modified_since):
        return False
    return True


def _has_extension(name: str, extensions: Iterable[str]) -> bool:
    """Return True if the filename ends with any extension."""
    name_lower = name.lower()
    return any(name_lower.endswith(ext) for ext in extensions)


def _is_newer(item: Dict, cutoff: datetime) -> bool:
    """Return True if the item was modified after the cutoff."""
    raw = item.get("lastModifiedDateTime")
    if not raw:
        return True
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    return ts >= cutoff.astimezone(timezone.utc)
