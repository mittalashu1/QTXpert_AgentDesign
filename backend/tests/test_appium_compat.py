from app.services.appium_compat import (
    ProviderLifecycleUnavailable,
    expected_package_state,
    safe_app_identity,
    safe_background_application,
    safe_page_source,
    safe_quit,
)


class ExplodingMobileMetadataDriver:
    capabilities = {"appium:appPackage": "com.qtx.demo", "appium:appActivity": ".MainActivity"}
    page_source = '<hierarchy package="com.qtx.demo"><node text="Welcome" /></hierarchy>'

    @property
    def current_package(self):  # pragma: no cover - must never be touched
        raise AssertionError("getCurrentPackage must not be called")

    @property
    def current_activity(self):  # pragma: no cover - must never be touched
        raise AssertionError("getCurrentActivity must not be called")

    def quit(self):
        raise RuntimeError("remote session already closed")


def test_identity_uses_capabilities_without_mobile_commands():
    identity = safe_app_identity(ExplodingMobileMetadataDriver())
    assert identity == {
        "package": "com.qtx.demo",
        "activity": ".MainActivity",
        "identity_source": "capabilities",
    }


def test_identity_falls_back_to_page_source_and_hint():
    class Driver:
        capabilities = {}
        page_source = '<hierarchy package="com.example.app" />'

    assert safe_app_identity(Driver())["package"] == "com.example.app"

    class EmptyDriver:
        capabilities = {}
        page_source = ""

    assert safe_app_identity(EmptyDriver(), package_hint="com.hint.app")["package"] == "com.hint.app"


def test_expected_package_state_is_tristate():
    driver = ExplodingMobileMetadataDriver()
    assert expected_package_state(driver, "com.qtx.demo") is True
    assert expected_package_state(driver, "com.other") is False

    class UnknownDriver:
        capabilities = {}
        page_source = ""

    assert expected_package_state(UnknownDriver(), "com.qtx.demo") is None


def test_evidence_and_cleanup_are_best_effort():
    class BrokenDriver:
        capabilities = {}

        @property
        def page_source(self):
            raise RuntimeError("hierarchy unavailable")

        def quit(self):
            raise RuntimeError("already gone")

    driver = BrokenDriver()
    assert safe_page_source(driver) == ""
    safe_quit(driver)


def test_background_falls_back_to_provider_supported_shell(monkeypatch):
    class Driver:
        calls = []

        def background_app(self, _seconds):
            raise RuntimeError('Unknown mobile command "backgroundApp"')

        def execute_script(self, command, arguments):
            self.calls.append((command, arguments))

    monkeypatch.setattr("app.services.appium_compat.time.sleep", lambda _seconds: None)
    driver = Driver()

    assert safe_background_application(driver, 2, package="com.qtx.demo") == "mobile_shell_home"
    assert driver.calls == [
        (
            "mobile: shell",
            {
                "command": "input",
                "args": ["keyevent", "3"],
                "includeStderr": True,
                "timeout": 5000,
            },
        )
    ]


def test_background_reports_provider_capability_block():
    class Driver:
        def background_app(self, _seconds):
            raise RuntimeError('Unknown mobile command "backgroundApp"')

        def execute_script(self, _command, _arguments):
            raise RuntimeError("mobile shell is disabled")

    try:
        safe_background_application(Driver(), 2, package="com.qtx.demo")
    except ProviderLifecycleUnavailable as exc:
        assert "custom/local Appium" in str(exc)
    else:  # pragma: no cover - assertion documents the required contract
        raise AssertionError("provider capability block was not raised")


def test_background_preserves_native_local_appium_path(monkeypatch):
    class Driver:
        def background_app(self, seconds):
            self.seconds = seconds

    monkeypatch.setattr("app.services.appium_compat.time.sleep", lambda _seconds: None)
    driver = Driver()

    assert safe_background_application(driver, 2, package="com.qtx.demo") == "background_app"
    assert driver.seconds == 2

