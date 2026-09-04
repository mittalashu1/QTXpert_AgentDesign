"""Focused tests for the secure Autopilot checkpoint input contract."""
from app.config import Settings
from app.schemas.autopilot import AutopilotInputSubmission, AutopilotRandomSpec
from app.services.autopilot_input_store import _fernet, generate_synthetic_value


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
