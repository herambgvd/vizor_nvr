import time
from app.recordings import download_tokens


def test_issue_and_verify():
    payload = download_tokens.issue("rec-123", "user-1")
    assert "token" in payload
    assert download_tokens.verify(payload["token"], "rec-123") == "user-1"


def test_single_use():
    payload = download_tokens.issue("rec-x", "user-2")
    assert download_tokens.verify(payload["token"], "rec-x") == "user-2"
    # Second use rejected
    assert download_tokens.verify(payload["token"], "rec-x") is None


def test_bound_to_recording():
    payload = download_tokens.issue("rec-a", "user-3")
    assert download_tokens.verify(payload["token"], "rec-b") is None
