"""security/redact: маскирование и детект секретов на приёме (§5.4)."""

from __future__ import annotations

import pytest

from appsecgate_master.security.redact import REDACTED, contains_suspected_secret, redact_text


@pytest.mark.parametrize(
    "text",
    [
        "AKIAIOSFODNN7EXAMPLE — токен в тексте",
        "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "api_key=superSecret1234567890",
        "DefaultEndpointsProtocol=https;AccountName=acc;AccountKey=dGVzdGtleTEyMzQ1Njc4OTBhYmNkZWY=",
    ],
)
def test_suspected_secret_detected(text: str):
    assert contains_suspected_secret(text)
    assert redact_text(text) != text


def test_clean_text_not_detected():
    text = "не критично, поправим в следующем спринте"
    assert not contains_suspected_secret(text)
    assert redact_text(text) == text


def test_redact_text_masks_in_place():
    assert REDACTED in redact_text("secret=1234567890abcdef0123456789abcdef")


def test_none_and_empty_are_safe():
    assert contains_suspected_secret(None) is False
    assert contains_suspected_secret("") is False
    assert redact_text("") == ""
