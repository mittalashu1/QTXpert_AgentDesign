import json

import pytest

from app.services.document_processor import UnsupportedDocumentTypeError, extract_text


def test_extract_txt():
    assert extract_text("req.txt", b"Hello world") == "Hello world"


def test_extract_md():
    assert extract_text("req.md", b"# Title\nBody") == "# Title\nBody"


def test_extract_jira_json():
    payload = {
        "issues": [
            {
                "key": "ABC-1",
                "fields": {"summary": "Login must support MFA", "description": "desc", "labels": ["auth"]},
            }
        ]
    }
    result = extract_text("export.json", json.dumps(payload).encode("utf-8"))
    assert "ABC-1" in result
    assert "Login must support MFA" in result


def test_unsupported_extension_raises():
    with pytest.raises(UnsupportedDocumentTypeError):
        extract_text("malware.exe", b"binary")
