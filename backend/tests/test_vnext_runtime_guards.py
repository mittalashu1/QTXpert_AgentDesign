import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from appium.webdriver.errorhandler import MobileErrorHandler
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from selenium.common.exceptions import NoSuchElementException

from app.api.middleware import RateLimitMiddleware
from app.config import Settings
from app.schemas.autopilot import AutopilotDiscoveryRequest, DiscoveredScreen
from app.services.autopilot_discovery import AutopilotDiscoveryService
from app.services.local_autopilot import LocalAndroidTarget, LocalAutopilotTransport


@pytest.mark.asyncio
async def test_android_discovery_keeps_unreachable_frontier_partial(tmp_path, monkeypatch):
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"apk")

    class Prototype:
        async def load_job(self, _job_id):
            return {"apk_path": str(apk), "filename": apk.name}

        async def load_analysis(self, _job_id):
            return SimpleNamespace(package_name="com.qtx.demo", main_activity=".MainActivity")

        def resolve_appium_url(self, _request):
            return "http://127.0.0.1:4723"

        async def _stop_device_farm_session(self, _service, _session):
            return None

    service = AutopilotDiscoveryService(Settings(), Prototype())
    monkeypatch.setattr(service, "_run_sync", lambda *args, **kwargs: {
        "screens": [DiscoveredScreen(screen_id="screen-1", fingerprint="demo")],
        "transitions": [], "actions_attempted": 1, "warnings": [],
        "target_ready": True, "interactive_surface_ready": True,
        "stop_reason": "Discovery stopped with 2 controls beyond the routes it could reopen.",
        "unvisited_edge_count": 2, "frontier_unreachable": True,
    })
    request = AutopilotDiscoveryRequest(provider="appium")

    first = await service.run("demo", request)
    assert first.status == "partial" and first.can_continue and first.exploration_cursor

    repeated = await service.run("demo", request, previous_discovery=first)
    assert repeated.status == "partial" and not repeated.can_continue
    assert repeated.unvisited_edge_count == 2


def test_runner_rpc_rate_does_not_consume_browser_quota():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, settings=Settings(RATE_LIMIT_PER_MINUTE=2))
    runner_rpc = "/api/v1/local-runners/11111111-1111-1111-1111-111111111111/autopilot/claim"

    @app.post(runner_rpc)
    @app.get("/api/v1/history")
    async def endpoint():
        return Response(status_code=204)

    headers = {"Authorization": f"Bearer qtxrunner_{'a' * 64}"}
    with TestClient(app) as client:
        for _ in range(65):
            assert client.post(runner_rpc, headers=headers).status_code == 204
        assert client.get("/api/v1/history").status_code == 204
        assert client.post(runner_rpc).status_code == 204
        assert client.get("/api/v1/history", headers=headers).status_code == 429
        assert client.post(runner_rpc, headers=headers).status_code == 204


@pytest.mark.asyncio
async def test_paired_android_raises_an_appium_error_for_a_missing_locator(monkeypatch):
    target = LocalAndroidTarget(uuid4(), uuid4(), uuid4(), uuid4(), "qa-usb", "com.qtx.demo", "a" * 64)
    transport = LocalAutopilotTransport(Settings(), target)

    async def exchange(command, _params):
        if command == "findElement":
            return {"status": "no such element", "value": {"message": "Native control missing"}}
        return {"value": []}

    monkeypatch.setattr(transport, "_exchange", exchange)
    connection = transport.connection()
    failure = await asyncio.to_thread(connection.execute, "findElement", {})
    with pytest.raises(NoSuchElementException, match="Native control missing"):
        MobileErrorHandler().check_response(failure)
    assert await asyncio.to_thread(connection.execute, "findElements", {}) == {"value": []}
