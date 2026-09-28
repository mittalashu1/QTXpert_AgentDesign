from types import SimpleNamespace

import pytest

from app.services.appium_compat import ProviderLifecycleUnavailable, enter_observed_text


def test_targeted_replacement_recovers_silent_keyboard_and_set_text_failure():
    state = {"focused": False, "text": "", "scripts": []}

    def clear():
        state.update(focused=False, text="")

    def click():
        state["focused"] = True

    def script(command, arguments):
        assert state["focused"] is True
        state["scripts"].append(command)
        if command == "mobile: replaceElementValue":
            assert arguments["elementId"] == "observed-input-id"
            state["text"] = arguments["text"]

    element = SimpleNamespace(
        id="observed-input-id", clear=clear, click=click,
        send_keys=lambda _value: None, get_attribute=lambda _name: state["text"],
    )
    assert enter_observed_text(SimpleNamespace(execute_script=script), element, "synthetic-input", verify_text=True) is True
    assert state["scripts"] == ["mobile: type", "mobile: replaceElementValue"]


def test_unreadable_flutter_text_retries_same_field_with_standard_entry():
    state = {"text": "", "operations": []}

    def clear():
        state["text"] = ""
        state["operations"].append("clear")

    def send_keys(value):
        state["text"] = value
        state["operations"].append("send_keys")

    def script(command, _arguments):
        assert command == "mobile: type"
        state["operations"].append("mobile_type_unconfirmed")

    element = SimpleNamespace(
        clear=clear, click=lambda: None, send_keys=send_keys,
        get_attribute=lambda _name: None,
    )
    assert enter_observed_text(
        SimpleNamespace(execute_script=script), element, "synthetic-input", verify_text=True,
    ) is None
    assert state["text"] == "synthetic-input"
    assert state["operations"] == [
        "clear", "mobile_type_unconfirmed", "clear", "send_keys",
    ]


def test_secure_input_uses_observed_element_without_reading_password_back():
    operations = []
    element = SimpleNamespace(
        clear=lambda: operations.append("clear"),
        click=lambda: operations.append("focus"),
        send_keys=lambda _value: operations.append("send_keys"),
        get_attribute=lambda _name: pytest.fail("secure field must not be read back"),
    )
    driver = SimpleNamespace(execute_script=lambda *_args: pytest.fail("keyboard extension must not be used"))
    assert enter_observed_text(
        driver, element, "synthetic-secret", verify_text=False, prefer_element_entry=True,
    ) is None
    assert operations == ["clear", "focus", "send_keys"]


def test_input_provider_error_never_exposes_supplied_value():
    def fail(command, arguments):
        raise RuntimeError("provider echoed " + arguments["text"])

    element = SimpleNamespace(clear=lambda: None, click=lambda: None)
    with pytest.raises(ProviderLifecycleUnavailable) as caught:
        enter_observed_text(SimpleNamespace(execute_script=fail), element, "synthetic-secret")
    assert "synthetic-secret" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_ios_uses_standard_entry_after_clear_restores_focus():
    operations = []
    element = SimpleNamespace(
        clear=lambda: operations.append("clear"), click=lambda: operations.append("focus"),
        send_keys=lambda _value: operations.append("type"),
    )
    enter_observed_text(SimpleNamespace(), element, "synthetic-input", target_kind="ios")
    assert operations == ["clear", "focus", "type"]
