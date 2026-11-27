"""Portable authored test steps and UAT verification contracts."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SafeReference = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{4,128}$")]
FixtureKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class FixtureBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: UUID
    part: Literal["value", "username", "password"] = "value"


class FixtureBindingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bindings: dict[FixtureKey, FixtureBinding] = Field(max_length=40)


class LedgerExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["add_money", "send_money"]
    outcome: Literal["posted", "rejected"]
    account_alias: SafeReference
    seed_reference: SafeReference
    cleanup_reference: SafeReference
    amount_minor: int = Field(ge=-100_000_000_000, le=100_000_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def check_amount(self):
        if self.outcome == "posted" and self.amount_minor <= 0:
            raise ValueError("A posted money movement requires a positive amount.")
        return self


class AuthoredStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["navigate", "tap", "fill", "back", "assert_text", "assert_visible", "capture_reference"]
    locator: str | None = Field(default=None, min_length=1, max_length=700)
    strategy: Literal["css", "accessibility_id", "id", "xpath"] | None = None
    value: str | None = Field(default=None, min_length=1, max_length=1000)
    input_key: FixtureKey | None = None

    @model_validator(mode="after")
    def check_fields(self):
        needs_locator = self.action in {"tap", "fill", "assert_visible", "capture_reference"}
        if needs_locator != bool(self.locator and self.strategy) or (
            not needs_locator and (self.locator or self.strategy)
        ):
            raise ValueError("Supply a locator and strategy only for actions that identify a control.")
        if (self.action in {"navigate", "assert_text"}) != bool(self.value):
            raise ValueError("Supply a value for navigation or a text assertion.")
        if (self.action == "fill") != bool(self.input_key):
            raise ValueError("A fill requires a Test Data key.")
        return self


class AuthoredAutomation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_kind: Literal["android", "ios", "web"]
    steps: list[AuthoredStep] = Field(min_length=1, max_length=100)
    outcome: LedgerExpectation | None = None

    @model_validator(mode="after")
    def check_steps(self):
        if not any(step.action in {"assert_text", "assert_visible"} for step in self.steps):
            raise ValueError("An executable case must include a UI assertion.")
        for step in self.steps:
            if step.action == "navigate" and self.target_kind != "web":
                raise ValueError("A navigate step requires a web target.")
            if step.strategy and (step.strategy == "css") != (self.target_kind == "web"):
                raise ValueError("The locator strategy must match the target platform.")
        captures = [step for step in self.steps if step.action == "capture_reference"]
        if self.outcome is not None:
            if len(captures) != 1 or self.steps[-1].action != "capture_reference":
                raise ValueError("A ledger-backed case must end by capturing its exact receipt or attempt reference.")
        elif captures:
            raise ValueError("A receipt capture requires a ledger outcome contract.")
        return self


class SignedLedgerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_record: SafeReference
    reference: SafeReference
    operation: Literal["add_money", "send_money"]
    account_alias: SafeReference
    seed_reference: SafeReference
    cleanup_reference: SafeReference
    decision: Literal["posted", "rejected"]
    posted_count: int = Field(ge=0, le=1000)
    amount_minor: int = Field(ge=-100_000_000_000, le=100_000_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    observed_at: datetime
    decision_at: datetime
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("observed_at", "decision_at")
    @classmethod
    def require_timezone(cls, value):
        if value.utcoffset() is None:
            raise ValueError("Ledger observation time must include a time zone.")
        return value.astimezone(timezone.utc)
