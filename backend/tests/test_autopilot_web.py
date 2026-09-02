from pathlib import Path

import pytest

from app.services.autopilot_web import _capture_screenshot


class _ScreenshotPage:
    def __init__(self, fail_full_page: bool = False, fail_viewport: bool = False):
        self.fail_full_page = fail_full_page
        self.fail_viewport = fail_viewport
        self.calls: list[dict] = []

    async def screenshot(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("full_page") and self.fail_full_page:
            raise TimeoutError("font wait timed out")
        if not kwargs.get("full_page") and self.fail_viewport:
            raise TimeoutError("viewport capture timed out")


@pytest.mark.asyncio
async def test_screenshot_falls_back_to_viewport_after_full_page_timeout(tmp_path: Path):
    page = _ScreenshotPage(fail_full_page=True)

    captured, warning = await _capture_screenshot(page, tmp_path / "launch.png")

    assert captured == str(tmp_path / "launch.png")
    assert warning and "viewport evidence captured" in warning
    assert [call["full_page"] for call in page.calls] == [True, False]


@pytest.mark.asyncio
async def test_screenshot_is_optional_when_both_capture_modes_fail(tmp_path: Path):
    page = _ScreenshotPage(fail_full_page=True, fail_viewport=True)

    captured, warning = await _capture_screenshot(page, tmp_path / "launch.png")

    assert captured is None
    assert warning and warning.startswith("Screenshot unavailable:")
    assert [call["full_page"] for call in page.calls] == [True, False]

