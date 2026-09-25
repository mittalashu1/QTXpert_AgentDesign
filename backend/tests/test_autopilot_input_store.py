"""Focused tests for the secure Autopilot checkpoint input contract."""
from datetime import datetime, timezone
from uuid import UUID

from app.config import Settings
from app.database.models.autopilot_input import AutopilotInputRecord
from app.schemas.autopilot import AutopilotInputSubmission, AutopilotRandomSpec
from app.services.autopilot_input_store import (
    AutopilotInputStoreError,
    _current_submissions,
    _fernet,
    _metadata,
    generate_synthetic_value,
)


def test_sensitive_values_are_fernet_encrypted_and_not_recoverable_from_metadata():
    settings = Settings(JWT_SECRET="unit-test-secret")
    plaintext = "SmokePassword!not-real"
    ciphertext = _fernet(settings).encrypt(plaintext.encode()).decode("ascii")
    assert plaintext not in ciphertext
    assert _fernet(settings).decrypt(ciphertext.encode()).decode() == plaintext


def test_random_generators_are_bounded_and_non_production():
    digits = generate_synthetic_value(AutopilotRandomSpec(kind="digits", length=8, seed="smoke"))
    amount = float(generate_synthetic_value(AutopilotRandomSpec(kind="amount", minimum=10, maximum=20, seed="smoke")))
    email = generate_synthetic_value(AutopilotRandomSpec(kind="email", length=8, seed="smoke"))
    assert len(digits) == 8 and digits.isdigit()
    assert 10 <= amount <= 20
    assert email.endswith("@example.test")


def test_checkpoint_decisions_accept_skip_reuse_and_random_without_a_value():
    for decision in ("skip", "reuse", "random"):
        submission = AutopilotInputSubmission(key="runtime_demo", decision=decision)
        assert submission.decision == decision


def test_obsolete_skip_only_checkpoint_does_not_block_current_inputs():
    submissions = [
        AutopilotInputSubmission(key="old_reset_hook", decision="skip"),
        AutopilotInputSubmission(key="current_username", decision="reuse"),
    ]

    accepted = _current_submissions(submissions, {"current_username": object()})

    assert [item.key for item in accepted] == ["current_username"]


def test_obsolete_checkpoint_cannot_write_or_reuse_a_value():
    for submission in (
        AutopilotInputSubmission(key="old_password", decision="provide", value="not-a-real-secret"),
        AutopilotInputSubmission(key="old_password", decision="reuse"),
    ):
        try:
            _current_submissions([submission], {})
        except AutopilotInputStoreError as exc:
            assert "no longer part of this analysis" in str(exc)
        else:
            raise AssertionError("stale value decisions must not be accepted")


def test_checkpoint_metadata_never_exposes_the_encrypted_value():
    plaintext = "qa-password-not-real"
    record = AutopilotInputRecord(
        owner_id=UUID("11111111-1111-1111-1111-111111111111"),
        project_id=UUID("22222222-2222-2222-2222-222222222222"),
        job_id="33333333-3333-3333-3333-333333333333",
        surface_key="uae-fintech-android-build",
        input_key="credential_reference",
        label="UAT sign-in credentials",
        category="credential",
        decision="provide",
        save_for_reuse=True,
        encrypted_value=_fernet(Settings(JWT_SECRET="unit-test-secret")).encrypt(plaintext.encode()).decode("ascii"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    metadata = _metadata(record)
    assert metadata.has_value is True
    assert plaintext not in metadata.model_dump_json()
    assert record.encrypted_value not in metadata.model_dump_json()
