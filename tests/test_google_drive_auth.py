"""Offline checks for the narrow Drive authorization helper."""

from __future__ import annotations

from io import BytesIO
import urllib.error

from scripts import google_drive_auth


def test_pkce_challenge_is_url_safe() -> None:
    challenge = google_drive_auth._challenge("test-verifier")
    assert len(challenge) == 43
    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge


def test_existing_folder_may_be_invisible_under_file_scope(monkeypatch) -> None:
    urls: list[str] = []

    def fake_request(url: str, **_kwargs: object) -> dict:
        urls.append(url)
        if google_drive_auth.KNOWN_FOLDER_ID in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        return {"files": []}

    monkeypatch.setattr(google_drive_auth, "_request_json", fake_request)
    assert google_drive_auth._check_drive("synthetic") == (True, False)
    assert "pageSize=1" in urls[0]


def test_existing_folder_visible(monkeypatch) -> None:
    monkeypatch.setattr(google_drive_auth, "_request_json", lambda *_args, **_kwargs: {})
    assert google_drive_auth._check_drive("synthetic") == (True, True)


def test_copied_callback_requires_current_state_and_port() -> None:
    url = "http://127.0.0.1:54321/?code=synthetic&state=expected"
    assert google_drive_auth._callback_values(url, "expected", 54321) == {"code": "synthetic"}
    assert "error" in google_drive_auth._callback_values(url, "other", 54321)
    assert "error" in google_drive_auth._callback_values(url, "expected", 12345)


def test_oauth_error_name_exposes_only_known_identifier() -> None:
    error = urllib.error.HTTPError("https://example.invalid", 400, "Bad Request", None, BytesIO(b'{"error":"invalid_grant"}'))
    assert google_drive_auth._oauth_error_name(error) == "invalid_grant"
    error = urllib.error.HTTPError("https://example.invalid", 400, "Bad Request", None, BytesIO(b'{"error":"arbitrary details"}'))
    assert google_drive_auth._oauth_error_name(error) == "unknown"
