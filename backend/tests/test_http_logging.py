import logging


def test_http_client_loggers_do_not_emit_request_urls_at_info():
    # httpx INFO messages include full request URLs, which can contain
    # short-lived presigned upload tokens.
    import app.main  # noqa: F401

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
