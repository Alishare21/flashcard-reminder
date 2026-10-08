"""Offline tests for idempotent app-owned Drive folder setup."""

from __future__ import annotations

from scripts import google_drive_setup


def test_uses_saved_folder_without_creating(monkeypatch) -> None:
    calls: list[str] = []

    def fake_request(url: str, _token: str, **_kwargs: object) -> dict:
        calls.append(url)
        return {"id": "saved", "mimeType": google_drive_setup.FOLDER_MIME}

    monkeypatch.setattr(google_drive_setup, "request_json", fake_request)
    assert google_drive_setup.ensure_folder("synthetic", "saved") == "saved"
    assert len(calls) == 1


def test_creates_folder_only_when_no_match(monkeypatch) -> None:
    calls: list[dict | None] = []

    def fake_request(_url: str, _token: str, *, body: dict | None = None) -> dict:
        calls.append(body)
        return {"files": []} if body is None else {"id": "new", "mimeType": google_drive_setup.FOLDER_MIME}

    monkeypatch.setattr(google_drive_setup, "request_json", fake_request)
    assert google_drive_setup.ensure_folder("synthetic", None) == "new"
    assert calls == [None, {"name": google_drive_setup.FOLDER_NAME, "mimeType": google_drive_setup.FOLDER_MIME}]
