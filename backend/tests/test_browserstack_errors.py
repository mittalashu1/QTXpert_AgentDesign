from app.services.browserstack_errors import upload_error_message


def test_upload_error_explains_testing_time_entitlement_without_app_timeout_blame():
    message = upload_error_message(
        403,
        '{"error":"[BROWSERSTACK_TESTING_TIME_LIMIT_EXHAUSTED] App Automate testing time has expired"}',
    )

    assert "account used by the Render credentials has no testing time available" in message
    assert "QTXpert's request timeout was not reached" in message
    assert "did not start a device session" in message
    assert "same App Automate account" in message


def test_upload_error_identifies_invalid_credentials_without_echoing_response_body():
    message = upload_error_message(401, "sensitive provider response content")

    assert "rejected the configured credentials (401)" in message
    assert "sensitive provider response content" not in message


def test_unknown_upload_error_keeps_provider_detail_for_diagnosis():
    message = upload_error_message(422, "invalid app archive")

    assert message == "BrowserStack app upload failed (422): invalid app archive"

