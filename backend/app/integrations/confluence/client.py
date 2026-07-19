"""
Confluence Cloud OAuth2 client - retrieves Functional Specs, Architecture
pages, and attachments, as called for by Method 4 of the input spec.
Shares the Atlassian OAuth flow with Jira but requests Confluence scopes.
"""
from typing import Any, Dict, List
from urllib.parse import urlencode

import httpx

from app.config import Settings


class ConfluenceNotConfiguredError(RuntimeError):
    pass


class ConfluenceClient:
    AUTH_BASE_URL = "https://auth.atlassian.com"
    API_BASE_URL = "https://api.atlassian.com"

    def __init__(self, settings: Settings):
        if not all(
            [
                settings.CONFLUENCE_URL,
                settings.CONFLUENCE_CLIENT_ID,
                settings.CONFLUENCE_CLIENT_SECRET,
                settings.CONFLUENCE_REDIRECT_URI,
            ]
        ):
            raise ConfluenceNotConfiguredError(
                "CONFLUENCE_URL, CONFLUENCE_CLIENT_ID, CONFLUENCE_CLIENT_SECRET, and "
                "CONFLUENCE_REDIRECT_URI must all be set to use the Confluence integration."
            )
        self._settings = settings

    def build_authorize_url(self, state: str) -> str:
        params = {
            "audience": "api.atlassian.com",
            "client_id": self._settings.CONFLUENCE_CLIENT_ID,
            "scope": "read:confluence-content.all read:confluence-space.summary offline_access",
            "redirect_uri": self._settings.CONFLUENCE_REDIRECT_URI,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
        return f"{self.AUTH_BASE_URL}/authorize?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.AUTH_BASE_URL}/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "client_id": self._settings.CONFLUENCE_CLIENT_ID,
                    "client_secret": self._settings.CONFLUENCE_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": self._settings.CONFLUENCE_REDIRECT_URI,
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_page(self, access_token: str, cloud_id: str, page_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.API_BASE_URL}/ex/confluence/{cloud_id}/wiki/api/v2/pages/{page_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"body-format": "storage"},
            )
            response.raise_for_status()
            return response.json()

    async def list_space_pages(
        self, access_token: str, cloud_id: str, space_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.API_BASE_URL}/ex/confluence/{cloud_id}/wiki/api/v2/spaces/{space_id}/pages",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"limit": limit},
            )
            response.raise_for_status()
            return response.json().get("results", [])
