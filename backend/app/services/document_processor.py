"""Extracts plain text from uploaded requirement documents.

Supports every format the spec's Method 1 (BRD upload) and Method 2 (Jira
export) call for. Adding a new extension only requires registering another
entry in `_EXTRACTORS` - callers never branch on file type themselves.
"""
import csv
import io
import json
from pathlib import Path
from typing import Callable, Dict

import docx  # python-docx
from pypdf import PdfReader


class UnsupportedDocumentTypeError(ValueError):
    pass


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    paragraphs = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            paragraphs.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(paragraphs)


def _extract_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _extract_jira_json(data: bytes) -> str:
    payload = json.loads(data)
    issues = payload.get("issues", payload if isinstance(payload, list) else [])
    lines = []
    for issue in issues:
        fields = issue.get("fields", issue)
        key = issue.get("key", fields.get("key", ""))
        summary = fields.get("summary", "")
        description = fields.get("description", "")
        acceptance_criteria = fields.get("customfield_acceptance_criteria", "")
        labels = ", ".join(fields.get("labels", []) or [])
        comments = fields.get("comment", {}).get("comments", []) if isinstance(
            fields.get("comment"), dict
        ) else []
        comment_text = "\n".join(c.get("body", "") for c in comments)
        lines.append(
            f"[{key}] {summary}\nDescription: {description}\n"
            f"Acceptance Criteria: {acceptance_criteria}\nLabels: {labels}\n"
            f"Comments: {comment_text}\n"
        )
    return "\n---\n".join(lines)


def _extract_csv(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    lines = []
    for row in reader:
        lines.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
    return "\n".join(lines)


_EXTRACTORS: Dict[str, Callable[[bytes], str]] = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".txt": _extract_text,
    ".md": _extract_text,
    ".json": _extract_jira_json,
    ".csv": _extract_csv,
}


def extract_text(filename: str, data: bytes) -> str:
    """Returns plain text extracted from an uploaded file's bytes."""
    extension = Path(filename).suffix.lower()
    extractor = _EXTRACTORS.get(extension)
    if extractor is None:
        raise UnsupportedDocumentTypeError(
            f"Unsupported file extension '{extension}'. Supported: {list(_EXTRACTORS)}"
        )
    return extractor(data)
