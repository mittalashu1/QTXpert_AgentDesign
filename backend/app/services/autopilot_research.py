"""Bounded public research used by the Autopilot context editor.

This is deliberately a small, dependency-free search adapter.  It fetches
public search-result metadata only (never a customer page's private area,
never a form and never a credential), caps the response, and returns source
signals as hypotheses.  Runtime Discovery remains the only proof of a live
workflow.
"""

from __future__ import annotations

import html
import html.parser
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.schemas.autopilot import AutopilotContextRequest, AutopilotScopeSource


class _SearchParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._result: dict[str, str] | None = None
        self._field: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).lower(): value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if tag.lower() == "a" and "result__a" in classes:
            if self._result is not None:
                self.results.append(self._result)
            self._result = {"url": values.get("href", ""), "title": "", "snippet": ""}
            self._field = "title"
        elif self._result is not None and tag.lower() in {"a", "div", "span"} and "result__snippet" in classes:
            self._field = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if self._result is None:
            return
        if tag.lower() == "a" and self._field == "title":
            self._field = None
        elif tag.lower() == "div" and self._field == "snippet":
            self._field = None
        # Search result links are closed before the snippet, so keep the result
        # until the next result starts or parsing completes.

    def handle_data(self, data: str) -> None:
        if self._result is None or not self._field:
            return
        value = re.sub(r"\s+", " ", html.unescape(data)).strip()
        if value:
            self._result[self._field] = (self._result.get(self._field, "") + " " + value).strip()

    def close(self) -> None:
        if self._result is not None:
            self.results.append(self._result)
            self._result = None
        super().close()


def _safe_text(value: object, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    # Search snippets can echo a pasted secret. Keep the same conservative
    # redaction boundary as the context writer.
    text = re.sub(
        r"(?i)\b(password|passcode|token|secret|otp|api[_ -]?key)\b\s*(?:is|as|[:=])\s*[^,; ]+",
        r"\1 [REDACTED]",
        text,
    )
    return text[:limit]


def _result_url(raw: str) -> str | None:
    value = html.unescape(raw or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        value = unquote(parse_qs(parsed.query).get("uddg", [""])[0])
        parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path or '/'}"[:500]


class AutopilotResearchService:
    """Fetch public search signals for one context-editing request."""

    SEARCH_URL = "https://html.duckduckgo.com/html/"

    @staticmethod
    def build_query(request: AutopilotContextRequest, profile_name: str) -> str:
        # Only identity and safe domain words enter the search query.  The
        # editable brief itself may contain secrets or internal URLs.
        name = _safe_text(request.application_name or request.build_name or "", 90)
        name = re.sub(r"[^\w .&-]", " ", name).strip()
        platform = _safe_text(request.platform, 30)
        profile = _safe_text(profile_name, 90)
        terms = [part for part in (name, profile, platform, "product features user journeys") if part]
        if request.profile_id == "uae_fintech" or any(token in profile.casefold() for token in ("bank", "wealth", "finance", "invest")):
            terms.extend(["UAE digital banking wealth", "CBUAE SCA consumer protection"])
        return " ".join(terms)[:320]

    async def research(
        self,
        request: AutopilotContextRequest,
        *,
        profile_name: str,
    ) -> tuple[list[AutopilotScopeSource], list[str]]:
        if not request.use_internet:
            return [], []
        query = self.build_query(request, profile_name)
        if not query:
            return [], ["Public research was skipped because no safe public application identity was supplied."]
        warnings: list[str] = []
        try:
            timeout = httpx.Timeout(8.0, connect=4.0)
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": "QTXpert-Autopilot/1.0 (public context research)"},
            ) as client:
                response = await client.get(self.SEARCH_URL, params={"q": query})
            if response.status_code >= 400:
                raise RuntimeError(f"search returned HTTP {response.status_code}")
            parser = _SearchParser()
            parser.feed(response.text[:256 * 1024])
            parser.close()
            sources: list[AutopilotScopeSource] = []
            seen: set[str] = set()
            retrieved = datetime.now(timezone.utc).isoformat()
            for raw in parser.results:
                url = _result_url(raw.get("url", ""))
                title = _safe_text(raw.get("title"), 180)
                snippet = _safe_text(raw.get("snippet"), 420)
                if not url or not title or url in seen:
                    continue
                seen.add(url)
                sources.append(
                    AutopilotScopeSource(
                        kind="internet",
                        label=title,
                        reference=url,
                        summary=snippet or "Public search result; verify against the target before treating it as scope.",
                        observed=False,
                        retrieved_at=retrieved,
                    )
                )
                if len(sources) >= 6:
                    break
            if not sources:
                warnings.append("Public research returned no usable results; context stayed evidence-led.")
            return sources, warnings
        except Exception as exc:  # pragma: no cover - network availability varies by environment
            warnings.append(f"Public research was unavailable ({type(exc).__name__}); context stayed evidence-led.")
            return [], warnings

