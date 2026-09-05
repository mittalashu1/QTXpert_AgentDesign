"""Shared safety helpers for local defect records and future connectors."""

from urllib.parse import urlparse

from app.services.document_intelligence import DocumentIntelligenceService


def secret_safe_text(value: object, limit: int = 1200) -> str:
    """Bound text and redact common secret key/value forms."""

    return DocumentIntelligenceService._redact_sensitive_text(str(value or ""), limit).strip()


def safe_target_reference(value: object, limit: int = 2048) -> str | None:
    """Return a target reference without credentials, query strings or fragments.

    Execution targets are useful triage metadata, but query strings frequently
    contain temporary tokens. Keep the origin/path only in defect snapshots and
    future tracker payloads.
    """

    raw = secret_safe_text(value, limit=4096)
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            # Drop optional userinfo before retaining the host/port portion.
            host = parsed.netloc.rsplit("@", 1)[-1]
            return f"{parsed.scheme.lower()}://{host}{parsed.path}"[:limit]
    except ValueError:
        pass
    return raw.split("?", 1)[0].split("#", 1)[0][:limit]
