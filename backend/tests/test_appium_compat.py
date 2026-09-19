from app.services.appium_compat import (
    ProviderLifecycleUnavailable,
    expected_package_state,
    observed_app_identity,
    safe_app_identity,
    safe_background_application,
    safe_page_source,
    safe_navigate_back,
    safe_quit,
    validate_target_surface,
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


def test_target_validation_rejects_system_only_surface():
    class Driver:
        capabilities = {"appium:appPackage": "com.qtx.demo"}
        page_source = (
            '<hierarchy><node package="com.android.systemui" '
            'resource-id="android:id/navigationBarBackground" class="android.view.View" />'
            '</hierarchy>'
        )

    ready, reason, identity = validate_target_surface(
        Driver(),
        expected_package="com.qtx.demo",
        page_source=Driver.page_source,
        control_labels=["navigationBarBackground"],
    )

    assert ready is False
    assert "system UI" in reason
    assert identity["hierarchy_packages"] == ["com.android.systemui"]


def test_target_validation_accepts_expected_package_in_live_hierarchy():
    class Driver:
        capabilities = {"appium:appPackage": "com.qtx.demo"}
        page_source = (
            '<hierarchy><node package="com.qtx.demo" class="android.widget.FrameLayout">'
            '<node text="Welcome" class="android.widget.TextView" />'
            '</node></hierarchy>'
        )

    ready, reason, identity = validate_target_surface(
        Driver(), expected_package="com.qtx.demo", page_source=Driver.page_source
    )

    assert ready is True
    assert "observed" in reason.lower()
    assert identity["package"] == "com.qtx.demo"


def test_target_validation_rejects_wrong_foreground_package():
    class Driver:
        capabilities = {"appium:appPackage": "com.qtx.demo"}
        page_source = '<hierarchy package="com.example.other"><node text="Other app" /></hierarchy>'

    ready, reason, _ = validate_target_surface(
        Driver(), expected_package="com.qtx.demo", page_source=Driver.page_source
    )

    assert ready is False
    assert "does not match" in reason


def test_target_validation_rejects_launcher_even_when_target_is_still_in_hierarchy():
    class Driver:
        capabilities = {"appium:appPackage": "com.qtx.demo"}
        page_source = (
            '<hierarchy><node package="com.qtx.demo" text="Welcome" />'
            '<node package="com.google.android.apps.nexuslauncher" '
            'text="Search apps, web and more" /></hierarchy>'
        )

    ready, reason, identity = validate_target_surface(
        Driver(), expected_package="com.qtx.demo", page_source=Driver.page_source
    )

    assert ready is False
    assert "com.google.android.apps.nexuslauncher" in reason
    assert identity["package"] == "com.qtx.demo"


def test_target_validation_rejects_launcher_when_target_package_is_unavailable():
    class Driver:
        capabilities = {"appium:appPackage": "com.qtx.demo"}
        page_source = (
            '<hierarchy package="com.google.android.apps.nexuslauncher">'
            '<node text="Search apps, web and more" /></hierarchy>'
        )

    ready, reason, _ = validate_target_surface(
        Driver(), page_source=Driver.page_source, control_labels=["Search apps, web and more"]
    )

    assert ready is False
    assert "Android launcher package" in reason


def test_target_validation_allows_capability_identity_when_hierarchy_omits_package():
    class Driver:
        capabilities = {"appium:appPackage": "com.qtx.demo"}
        page_source = '<hierarchy><node text="Welcome" class="android.widget.TextView" /></hierarchy>'

    ready, reason, identity = validate_target_surface(
        Driver(), expected_package="com.qtx.demo", page_source=Driver.page_source
    )

    assert ready is True
    assert "capabilities" in reason.lower()
    assert observed_app_identity(Driver(), page_source=Driver.page_source)["package"] == "com.qtx.demo"


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

def test_back_uses_provider_fallback_when_webdriver_back_is_unavailable():
    class Driver:
        def back(self):
            raise RuntimeError("Unknown command: back")

        def press_keycode(self, keycode):
            self.keycode = keycode

    driver = Driver()

    assert safe_navigate_back(driver, target_kind="android") == "android_back_keycode"
    assert driver.keycode == 4


def test_back_reports_provider_limitation_without_leaking_provider_error():
    class Driver:
        def back(self):
            raise RuntimeError("internal provider detail")

        def press_keycode(self, _keycode):
            raise RuntimeError("keycode unsupported")

        def execute_script(self, command, _arguments):
            if command == "mobile: pressKey":
                raise RuntimeError("pressKey unsupported")
            raise RuntimeError("shell unsupported")

    try:
        safe_navigate_back(Driver(), target_kind="android")
    except ProviderLifecycleUnavailable as exc:
        assert str(exc) == "Android back navigation is unavailable through this device provider."
        assert "internal provider detail" not in str(exc)
    else:  # pragma: no cover - assertion documents the required contract
        raise AssertionError("provider limitation was not reported")


def test_ios_back_does_not_try_android_keycode_fallback():
    class Driver:
        called = False

        def back(self):
            raise RuntimeError("generic back unsupported")

        def press_keycode(self, _keycode):
            self.called = True

    driver = Driver()

    try:
        safe_navigate_back(driver, target_kind="ios")
    except ProviderLifecycleUnavailable as exc:
        assert str(exc) == "Back navigation is unavailable through this device provider."
    else:  # pragma: no cover
        raise AssertionError("unsupported iOS back should be reported")
    assert driver.called is False
