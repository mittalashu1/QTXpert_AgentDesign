"""Schemas for the Android-first QTXpert Autopilot prototype."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class AutopilotTest(BaseModel):
    id: str
    suite: str
    title: str
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    objective: str
    steps: List[str] = Field(default_factory=list)
    expected: List[str] = Field(default_factory=list)
    autonomous: bool = True
    destructive: bool = False
    source: Literal["deterministic", "ai"] = "deterministic"


class AutopilotAnalysis(BaseModel):
    job_id: str
    filename: str
    platform: Literal["android"] = "android"
    status: Literal["analyzed", "analysis_partial"] = "analyzed"
    app_name: Optional[str] = None
    package_name: Optional[str] = None
    version_name: Optional[str] = None
    version_code: Optional[str] = None
    min_sdk: Optional[str] = None
    target_sdk: Optional[str] = None
    main_activity: Optional[str] = None
    activities: List[str] = Field(default_factory=list)
    services: List[str] = Field(default_factory=list)
    receivers: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    file_count: int = 0
    size_bytes: int = 0
    sha256: str
    debuggable: Optional[bool] = None
    inferred_domain: str = "General mobile application"
    app_summary: str = ""
    critical_journeys: List[str] = Field(default_factory=list)
    clarification_questions: List[str] = Field(default_factory=list)
    tests: List[AutopilotTest] = Field(default_factory=list)
    release_risks: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    capabilities: Dict[str, bool] = Field(default_factory=dict)


class AutopilotJobSummary(BaseModel):
    job_id: str
    filename: str
    status: str
    package_name: Optional[str] = None
    app_name: Optional[str] = None
    created_at: str


class AutopilotExecutionRequest(BaseModel):
    appium_url: str = "http://127.0.0.1:4723"
    device_name: str = "Android Emulator"
    platform_version: Optional[str] = None
    appium_app: Optional[str] = Field(
        default=None,
        description="Optional remote/cloud app reference. If omitted, the uploaded APK path is used.",
    )
    no_reset: bool = False
    auto_grant_permissions: bool = False


class AutopilotExecutionResult(BaseModel):
    job_id: str
    status: Literal["passed", "failed", "blocked"]
    started_at: str
    finished_at: str
    duration_seconds: float
    device_name: str
    current_package: Optional[str] = None
    current_activity: Optional[str] = None
    screenshot_path: Optional[str] = None
    page_source_path: Optional[str] = None
    error: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
