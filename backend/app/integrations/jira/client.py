"""
Jira Cloud OAuth2 (3-legged) client.

Retrieves Epics, Stories, Acceptance Criteria, Comments, Labels, and
Attachments for a project/issue as called for by Method 3 of the input
spec. Requires `JIRA_URL`, `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`, and
`JIRA_REDIRECT_URI` to be configured; without them the OAuth endpoints
will raise `LLMProviderError`-style configuration errors at call time
rather than silently no-op.
"""
from typing import Any, Dict, List
from urllib.parse import urlencode

import httpx

from app.config import Settings


class JiraNotConfiguredError(RuntimeError):
    pass


class JiraClient:
    AUTH_BASE_URL = "https://auth.atlassian.com"
    API_BASE_URL = "https://api.atlassian.com"

    def __init__(self, settings: Settings):
        if not all(
            [settings.JIRA_URL, settings.JIRA_CLIENT_ID, settings.JIRA_CLIENT_SECRET, settings.JIRA_REDIRECT_URI]
        ):
            raise JiraNotConfiguredError(
                "JIRA_URL, JIRA_CLIENT_ID, JIRA_CLIENT_SECRET, and JIRA_REDIRECT_URI "
                "must all be set to use the Jira integration."
            )
        self._settings = settings

    def build_authorize_url(self, state: str) -> str:
        params = {
            "audience": "api.atlassian.com",
            "client_id": self._settings.JIRA_CLIENT_ID,
            "scope": "read:jira-work read:jira-user offline_access",
            "redirect_uri": self._settings.JIRA_REDIRECT_URI,
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
                    "client_id": self._settings.JIRA_CLIENT_ID,
                    "client_secret": self._settings.JIRA_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": self._settings.JIRA_REDIRECT_URI,
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_accessible_resources(self, access_token: str) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.API_BASE_URL}/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()

    async def get_issue(
        self, access_token: str, cloud_id: str, issue_key: str
    ) -> Dict[str, Any]:
        """Retrieves an Epic/Story with fields, comments, labels, attachments."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.API_BASE_URL}/ex/jira/{cloud_id}/rest/api/3/issue/{issue_key}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"expand": "renderedFields,comments,attachment"},
            )
            response.raise_for_status()
            return response.json()

    async def search_issues(
        self, access_token: str, cloud_id: str, jql: str, max_results: int = 100
    ) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.API_BASE_URL}/ex/jira/{cloud_id}/rest/api/3/search",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"jql": jql, "maxResults": max_results},
            )
            response.raise_for_status()
            return response.json().get("issues", [])
