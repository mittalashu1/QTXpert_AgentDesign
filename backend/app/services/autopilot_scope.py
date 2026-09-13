"""Plain-language scope compilation for Autopilot.

Autopilot has several evidence producers (profile, user brief, repository
documents, public research and Runtime Discovery).  This module gives them a
single, versioned contract without allowing a profile or a web search result to
pretend that a workflow was observed.  It is intentionally deterministic so a
missing LLM never changes the safety boundary.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Sequence
from urllib.parse import urlparse

from app.schemas.autopilot import (
    AutopilotDiscoveryResult,
    AutopilotScope,
    AutopilotScopeSection,
    AutopilotScopeSource,
    AutopilotTest,
    AutopilotTestProvenance,
)


_DOCUMENT_SECTION_LABELS: tuple[tuple[str, str], ...] = (
    ("business rules", "Business rules"),
    ("functional requirements", "Functional requirements"),
    ("critical journeys", "Critical journeys"),
    ("acceptance criteria", "Acceptance criteria"),
    ("integrations", "Service connections"),
    ("dependencies", "Dependencies"),
    ("validation rules", "Validation rules"),
    ("regulatory requirements", "Regulatory expectations"),
    ("non-functional requirements", "Quality expectations"),
    ("security controls", "Security controls"),
    ("data rules", "Data rules"),
    ("error/recovery rules", "Error and recovery rules"),
    ("open questions", "Open questions"),
)

_TEST_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Core journeys", ("functional", "journey", "workflow", "feature")),
    ("Successful outcomes", ("positive", "happy path", "success")),
    ("Invalid and recovery paths", ("negative", "invalid", "boundary", "error", "recovery")),
    ("Business acceptance", ("uat", "user acceptance", "acceptance criteria")),
    ("Service connections", ("sit", "integration", "api", "backend", "contract", "webhook")),
    ("Screen clarity and accessibility", ("ui", "visual", "accessibility", "a11y", "wcag")),
    ("Speed and responsiveness", ("performance", "latency", "load", "throughput", "startup")),
    ("Security and privacy", ("security", "privacy", "permission", "authentication", "authorization")),
    ("Device and browser fit", ("compatibility", "device matrix", "browser")),
    ("Release comparison", ("regression", "baseline", "release comparison")),
)

_PLAIN_NON_FUNCTIONAL = (
    "Screen clarity and accessibility",
    "Speed and responsiveness",
    "Security and privacy",
    "Recovery from errors and interruptions",
)


def _clean(value: object, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _unique(values: Iterable[str], limit: int = 20) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _clean(value)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _target_label(target_kind: str, target_url: str | None, application_name: str | None, package_name: str | None) -> str:
    kind = (target_kind or "android").strip().lower()
    label = {"web": "Website", "ios": "iOS app", "android": "Android app"}.get(kind, kind.title())
    identity = _clean(application_name or package_name or "selected target", 160)
    if kind == "web" and target_url:
        parsed = urlparse(target_url)
        identity = _clean(parsed.netloc + (parsed.path.rstrip("/") or ""), 180) or identity
    return f"{label} · {identity}"


def _source_from_dict(raw: object) -> AutopilotScopeSource | None:
    if isinstance(raw, AutopilotScopeSource):
        return raw
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "internet").strip().lower()
    if kind not in {"profile", "user_context", "document", "internet", "target", "runtime", "system"}:
        kind = "internet"
    return AutopilotScopeSource(
        kind=kind,  # type: ignore[arg-type]
        label=_clean(raw.get("label") or raw.get("title") or "Public reference", 180),
        reference=_clean(raw.get("reference") or raw.get("url") or "", 500) or None,
        summary=_clean(raw.get("summary") or raw.get("snippet") or "", 420),
        observed=bool(raw.get("observed", False)),
        retrieved_at=_clean(raw.get("retrieved_at") or "", 80) or None,
    )


def _research_sources(raw_sources: Sequence[object] | None) -> list[AutopilotScopeSource]:
    result: list[AutopilotScopeSource] = []
    for raw in raw_sources or []:
        source = _source_from_dict(raw)
        if source is None:
            continue
        if source.kind != "internet":
            source = source.model_copy(update={"kind": "internet"})
        if source.reference and source.reference in {item.reference for item in result}:
            continue
        result.append(source)
    return result[:8]


def _document_sections(document_context: str, document_asset_ids: Sequence[str] | None, document_analysis_run_id: str | None) -> list[AutopilotScopeSection]:
    """Extract safe section headings from the Document Intelligence hand-off.

    The hand-off is already redacted and bounded by Document Intelligence.  We
    retain headings and short summaries rather than copying document bodies.
    This keeps report provenance useful while avoiding a second document store.
    """

    sections: list[AutopilotScopeSection] = []
    # A user's editable brief can contain words such as "requirements" or
    # "acceptance criteria".  Those are not document sections unless the
    # server has validated a repository asset or a completed Document
    # Intelligence run for this project.
    if not document_asset_ids and not document_analysis_run_id:
        return sections
    refs = [f"document:{str(value)}" for value in (document_asset_ids or [])[:20]]
    if document_analysis_run_id:
        refs.append(f"document-analysis:{document_analysis_run_id}")
    text = str(document_context or "")
    for index, line in enumerate(text.splitlines()):
        clean_line = _clean(line, 520)
        if not clean_line:
            continue
        repository_match = re.match(r"\[Repository document:\s*(.+?)\]", clean_line, re.IGNORECASE)
        if repository_match:
            filename = _clean(repository_match.group(1), 180)
            following = ""
            for candidate in text.splitlines()[index + 1 : index + 4]:
                if _clean(candidate):
                    following = _clean(candidate, 300)
                    break
            sections.append(
                AutopilotScopeSection(
                    key=f"document:{re.sub(r'[^a-z0-9]+', '-', filename.lower()).strip('-') or index}",
                    title=filename,
                    summary=following or "Stored project document linked to this scope.",
                    source="document",
                    source_refs=refs,
                    requested=True,
                )
            )
            continue
        for marker, title in _DOCUMENT_SECTION_LABELS:
            prefix = f"{marker}:"
            if clean_line.casefold().startswith(prefix):
                summary = _clean(clean_line.split(":", 1)[1], 360)
                sections.append(
                    AutopilotScopeSection(
                        key=f"document-section:{re.sub(r'[^a-z0-9]+', '-', marker).strip('-')}",
                        title=title,
                        summary=summary or "Section retained from the reviewed documentation baseline.",
                        source="document",
                        source_refs=refs,
                        requested=True,
                    )
                )
                break
        if clean_line.casefold().startswith("documents reviewed:"):
            names = _clean(clean_line.split(":", 1)[1], 520)
            sections.append(
                AutopilotScopeSection(
                    key="document-inventory",
                    title="Reviewed documents",
                    summary=names,
                    source="document",
                    source_refs=refs,
                    requested=True,
                )
            )
        elif clean_line.casefold().startswith("document sections retained:"):
            payload = _clean(clean_line.split(":", 1)[1], 520)
            for section_index, item in enumerate(re.split(r"\s*\|\s*", payload), start=1):
                if ":" not in item:
                    continue
                title, summary = item.split(":", 1)
                sections.append(
                    AutopilotScopeSection(
                        key=f"document-retained:{section_index}",
                        title=_clean(title, 180),
                        summary=_clean(summary, 360),
                        source="document",
                        source_refs=refs,
                        requested=True,
                    )
                )
    if (document_asset_ids or document_analysis_run_id) and not sections:
        sections.append(
            AutopilotScopeSection(
                key="document-baseline",
                title="Document Intelligence baseline",
                summary="Selected project documents are linked to this run; their findings remain static evidence until the target confirms them.",
                source="document",
                source_refs=refs,
                requested=True,
            )
        )
    # Avoid duplicate headings when the same line appears in a baseline and a
    # selected-document excerpt.
    unique: list[AutopilotScopeSection] = []
    seen: set[str] = set()
    for section in sections:
        if section.key in seen:
            continue
        seen.add(section.key)
        unique.append(section)
    return unique[:30]


def _context_sources(context: str) -> list[AutopilotScopeSource]:
    """Recover public reference signals appended by context generation."""

    sources: list[AutopilotScopeSource] = []
    for line in str(context or "").splitlines():
        if not line.casefold().startswith("public reference signals"):
            continue
        payload = line.split(":", 1)[1] if ":" in line else ""
        for item in re.split(r"\s*;\s*", payload):
            urls = re.findall(r"https?://[^\s)]+", item)
            url = urls[0].rstrip(".,") if urls else None
            title = re.sub(r"\s*\([^)]*https?://[^)]*\)", "", item).strip()
            title = _clean(title or (urlparse(url).netloc if url else "Public reference"), 180)
            if url:
                sources.append(
                    AutopilotScopeSource(
                        kind="internet",
                        label=title,
                        reference=url[:500],
                        summary="Public reference signal supplied to context generation; not execution evidence.",
                        observed=False,
                    )
                )
    return _research_sources([item.model_dump() for item in sources])


def _requested_types(context: str) -> list[str]:
    lowered = str(context or "").casefold()
    found: list[str] = []
    for label, terms in _TEST_TYPE_RULES:
        if any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered) for term in terms):
            found.append(label)
    if "Core journeys" not in found:
        found.insert(0, "Core journeys")
    return _unique(found, 12)


def _change_impact(context: str, document_sections: Sequence[AutopilotScopeSection]) -> list[str]:
    lines = [_clean(line, 420) for line in str(context or "").splitlines()]
    signals = [
        line for line in lines
        if any(term in line.casefold() for term in ("change", "impact", "release", "updated", "new feature", "modified", "regression"))
    ]
    result = [line for line in signals if not line.casefold().startswith("public reference signals")][:4]
    if any("change request" in section.title.casefold() or "release" in section.title.casefold() for section in document_sections):
        result.append("Reviewed documents include a change or release section; compare affected journeys with the current target.")
    if not result:
        result.append("No explicit change request was supplied; compare with the previous baseline when one is available.")
    return _unique(result, 6)


def _runtime_sections(discovery: AutopilotDiscoveryResult | None) -> list[AutopilotScopeSection]:
    if discovery is None or not discovery.screens:
        return []
    refs: list[str] = []
    for screen in discovery.screens[:40]:
        refs.append(f"runtime:{screen.screen_id}")
    sections: list[AutopilotScopeSection] = []
    seen: set[str] = set()
    for index, screen in enumerate(discovery.screens[:40], start=1):
        title = _clean(screen.page_label or screen.title or screen.activity_name or f"Observed screen {index}", 180)
        journey = _clean(screen.journey or "Observed journey", 180)
        key = f"runtime:{screen.screen_id}"
        if key in seen:
            continue
        seen.add(key)
        sections.append(
            AutopilotScopeSection(
                key=key,
                title=f"{journey} · {title}",
                summary=f"Runtime Discovery observed {len(screen.controls)} control(s) on this screen.",
                source="runtime",
                source_refs=[key],
                status="observed",
                requested=True,
            )
        )
    return sections


def _login_observed(discovery: AutopilotDiscoveryResult | None) -> bool:
    """Return true only when the live map contains a credential-like field.

    Profile language, document requirements and public search results never
    count as authentication evidence. Runtime Discovery's semantic controls
    are the only source used for this gate.
    """

    if discovery is None:
        return False
    if any(item.category == "credential" for item in discovery.input_requests):
        return True
    auth_terms = re.compile(
        r"\b(?:user\s*(?:id|name)|username|email|password|passcode|otp|mfa|sign\s*in|log\s*in|login)\b",
        re.IGNORECASE,
    )
    for screen in discovery.screens:
        for control in screen.controls:
            haystack = " ".join(
                (
                    control.semantic_label,
                    control.text,
                    control.content_description,
                    control.resource_id,
                    control.input_kind or "",
                )
            )
            if control.input_capable and (
                control.input_kind == "credential" or auth_terms.search(haystack)
            ):
                return True
    return False


def compile_scope(
    *,
    profile_id: str | None,
    profile_name: str | None,
    target_kind: str,
    target_url: str | None = None,
    application_name: str | None = None,
    package_name: str | None = None,
    context: str = "",
    document_asset_ids: Sequence[str] | None = None,
    document_analysis_run_id: str | None = None,
    document_context: str = "",
    research_sources: Sequence[object] | None = None,
    discovery: AutopilotDiscoveryResult | None = None,
) -> AutopilotScope:
    """Compile a concise, editable scope without making unsupported claims."""

    target_kind = (target_kind or "android").strip().lower()
    safe_profile = _clean(profile_name or profile_id or "Selected profile", 160)
    target = _target_label(target_kind, target_url, application_name, package_name)
    document_sections = _document_sections(
        document_context or context,
        [str(value) for value in (document_asset_ids or [])],
        str(document_analysis_run_id) if document_analysis_run_id else None,
    )
    sources = [
        AutopilotScopeSource(
            kind="profile",
            label=safe_profile,
            reference=f"profile:{_clean(profile_id or 'custom', 80)}",
            summary="Selected profile sets the business focus; it does not prove a product workflow.",
            observed=False,
        ),
        AutopilotScopeSource(
            kind="target",
            label=target,
            reference=f"target:{(target_kind or 'android').lower()}",
            summary="Static target metadata or public page evidence.",
            observed=True,
        ),
    ]
    if str(context or "").strip():
        sources.append(
            AutopilotScopeSource(
                kind="user_context",
                label="Editable testing brief",
                reference="context:editable-brief",
                summary="User-provided scope and priorities; claims remain unverified until observed.",
                observed=False,
            )
        )
    if document_sections:
        sources.append(
            AutopilotScopeSource(
                kind="document",
                label="Document Intelligence baseline",
                reference=(f"document-analysis:{document_analysis_run_id}" if document_analysis_run_id else "document:repository"),
                summary=f"{len(document_sections)} section(s) retained from the selected project documents.",
                observed=False,
            )
        )
    internet = _research_sources(research_sources) or _context_sources(context)
    sources.extend(internet)
    runtime = _runtime_sections(discovery)
    login_observed = _login_observed(discovery)
    if runtime:
        sources.append(
            AutopilotScopeSource(
                kind="runtime",
                label="Runtime Discovery",
                reference=f"runtime:{discovery.job_id}",
                summary=f"Observed {discovery.screen_count} screen(s) and {discovery.control_count} control(s).",
                observed=True,
            )
        )
    scope_sections = [
        AutopilotScopeSection(
            key="profile-scope",
            title="Business focus",
            summary=f"{safe_profile} focus for the selected target.",
            source="profile",
            source_refs=[f"profile:{_clean(profile_id or 'custom', 80)}"],
            requested=True,
        ),
        AutopilotScopeSection(
            key="target-surface",
            title="Target surface",
            summary=target,
            source="target",
            source_refs=[f"target:{(target_kind or 'android').lower()}"],
            status="observed",
            requested=True,
        ),
        *document_sections,
        *runtime,
    ]
    functional = ["Core journeys", "Navigation and safe interactions", "Positive and negative outcomes"]
    if target_kind == "web":
        functional.append("Public pages, links and forms")
    else:
        functional.append("Install, launch and app lifecycle")
    functional.extend(item for item in _requested_types(context) if item not in functional and item in {"Business acceptance", "Service connections", "Release comparison"})
    non_functional = list(_PLAIN_NON_FUNCTIONAL)
    if target_kind == "web":
        non_functional.append("Browser and device fit")
    else:
        non_functional.append("Device and OS fit")
    # Keep the user-facing scope short even when the model or documents are
    # verbose. Detailed provenance remains available in the source arrays.
    summary = (
        f"{target} is scoped for {safe_profile}. Start with safe, observable journeys; "
        + (
            "a sign-in form was observed, so authenticated execution remains gated on approved credentials."
            if login_observed
            else "authenticated execution stays out of scope until Runtime Discovery observes a sign-in form."
        )
    )
    authentication_gate = (
        "A sign-in form was observed by Runtime Discovery; approved non-production credentials are required before authenticated execution."
        if login_observed
        else "No sign-in form was observed by Runtime Discovery; continue with public/read-only coverage and do not request credentials."
        if runtime
        else "Runtime Discovery must observe a real sign-in form before authenticated execution."
    )
    return AutopilotScope(
        summary=summary[:500],
        target=target,
        functional_scope=_unique(functional, 8),
        non_functional_scope=_unique(non_functional, 8),
        requested_test_types=_requested_types(context),
        # Document Intelligence can carry release/change signals in its
        # bounded hand-off; include that hand-off in the change compiler while
        # keeping the original document bytes out of the scope object.
        change_impact=_change_impact(
            "\n".join(item for item in (context, document_context) if item),
            document_sections,
        ),
        document_sections=document_sections[:30],
        scope_sections=scope_sections[:50],
        sources=sources[:20],
        authentication_gate=authentication_gate,
        runtime_observed=bool(runtime),
        login_observed=login_observed,
    )


def add_test_provenance(
    test: AutopilotTest,
    *,
    target_kind: str,
    profile_id: str | None = None,
    context_present: bool = False,
    document_asset_ids: Sequence[str] | None = None,
    research_sources: Sequence[object] | None = None,
    runtime_discovery: AutopilotDiscoveryResult | None = None,
) -> AutopilotTest:
    """Attach a bounded, explainable source trail to one generated test."""

    items: list[AutopilotTestProvenance] = list(test.provenance or [])
    if not any(item.kind == "target" for item in items):
        items.append(
            AutopilotTestProvenance(
                kind="target",
                label="Target evidence",
                reference=f"target:{(target_kind or 'android').lower()}",
                observed=True,
            )
        )
    if profile_id:
        if not any(item.kind == "profile" for item in items):
            items.append(AutopilotTestProvenance(kind="profile", label="Selected profile", reference=f"profile:{profile_id}"))
    if context_present:
        if not any(item.kind == "user_context" for item in items):
            items.append(AutopilotTestProvenance(kind="user_context", label="Editable testing brief", reference="context:editable-brief"))
    for value in [str(item) for item in (document_asset_ids or [])[:4]]:
        ref = f"document:{value}"
        if not any(item.reference == ref for item in items):
            items.append(AutopilotTestProvenance(kind="document", label="Selected project document", reference=ref))
    for source in _research_sources(research_sources)[:2]:
        if not any(item.reference == source.reference for item in items):
            items.append(
                AutopilotTestProvenance(
                    kind="internet",
                    label=source.label,
                    reference=source.reference,
                    observed=False,
                )
            )
    if runtime_discovery is not None:
        refs = [
            screen
            for screen in runtime_discovery.screens
            if (test.page_label and test.page_label.casefold() in _clean(screen.page_label or screen.title).casefold())
            or (test.journey and test.journey.casefold() == _clean(screen.journey).casefold())
        ]
        if refs:
            ref = f"runtime:{refs[0].screen_id}"
            if not any(item.reference == ref for item in items):
                items.append(
                    AutopilotTestProvenance(
                        kind="runtime",
                        label="Observed Runtime Discovery screen",
                        reference=ref,
                        observed=True,
                    )
                )
        elif test.journey or test.page_label:
            ref = f"runtime:{runtime_discovery.job_id}"
            if not any(item.reference == ref for item in items):
                items.append(
                    AutopilotTestProvenance(
                        kind="runtime",
                        label="Observed Runtime Discovery map",
                        reference=ref,
                        observed=True,
                    )
                )
    # AI is a planner, not evidence. Keep it visible as a source only when the
    # case was generated by the model; the target/profile trail remains first.
    if test.source == "ai":
        if not any(item.reference == "ai:planner" for item in items):
            items.append(AutopilotTestProvenance(kind="system", label="AI plan suggestion", reference="ai:planner", observed=False))
    return test.model_copy(update={"provenance": items[:12]})


def update_scope_with_discovery(scope: AutopilotScope, discovery: AutopilotDiscoveryResult) -> AutopilotScope:
    """Merge observed screens into a prior scope without losing its sources."""

    additions = _runtime_sections(discovery)
    existing_scope_sections = list(scope.scope_sections or scope.document_sections)
    existing_keys = {item.key for item in existing_scope_sections}
    merged_scope_sections = [
        *existing_scope_sections,
        *(item for item in additions if item.key not in existing_keys),
    ]
    document_sections = [
        item for item in (scope.document_sections or existing_scope_sections)
        if item.source == "document"
    ]
    sources = list(scope.sources)
    runtime_ref = f"runtime:{discovery.job_id}"
    if not any(item.reference == runtime_ref for item in sources):
        sources.append(
            AutopilotScopeSource(
                kind="runtime",
                label="Runtime Discovery",
                reference=runtime_ref,
                summary=f"Observed {discovery.screen_count} screen(s) and {discovery.control_count} control(s).",
                observed=True,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    functional = list(scope.functional_scope)
    if "Observed safe journeys" not in functional:
        functional.append("Observed safe journeys")
    login_observed = _login_observed(discovery)
    return scope.model_copy(
        update={
            "document_sections": document_sections[:30],
            "scope_sections": merged_scope_sections[:50],
            "sources": sources[:20],
            "functional_scope": _unique(functional, 8),
            "runtime_observed": True,
            "login_observed": login_observed,
            "authentication_gate": (
                "A sign-in form was observed by Runtime Discovery; approved non-production credentials are required before authenticated execution."
                if login_observed
                else "No sign-in form was observed by Runtime Discovery; continue with public/read-only coverage and do not request credentials."
            ),
        }
    )

