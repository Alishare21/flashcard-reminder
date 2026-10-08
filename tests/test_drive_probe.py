"""Offline tests for the count-only Trigger Drive probe."""

from __future__ import annotations

import pytest

from src import drive_probe


SETTINGS = {
    "GOOGLE_CLIENT_ID": "synthetic-id",
    "GOOGLE_CLIENT_SECRET": "synthetic-secret",
    "GOOGLE_REFRESH_TOKEN": "synthetic-refresh",
    "GOOGLE_DRIVE_NOTES_FOLDER_ID": "synthetic-folder",
}


def test_probe_returns_counts_without_card_text(monkeypatch) -> None:
    def fake_request(request) -> dict:
        url = request.full_url
        if "oauth2.googleapis.com" in url:
            return {"access_token": "synthetic-access"}
        if "appDataFolder" in url:
            return {"files": []}
        if "/synthetic-folder?" in url:
            return {"mimeType": drive_probe.FOLDER_MIME}
        return {"files": [{"name": "one.md"}, {"name": "two.MD"}, {"name": "other.txt"}]}

    monkeypatch.setattr(drive_probe, "_json_request", fake_request)
    result = drive_probe.check_drive(SETTINGS)
    assert result == {"status": "passed", "app_data_reachable": True, "notes_folder_reachable": True, "markdown_files": 2}
    assert "synthetic-secret" not in str(result)


def test_probe_rejects_missing_credentials_before_network(monkeypatch) -> None:
    monkeypatch.setattr(drive_probe, "_json_request", lambda _request: pytest.fail("Unexpected network call"))
    with pytest.raises(ValueError, match="missing"):
        drive_probe.check_drive({})


def test_probe_counts_all_pages(monkeypatch) -> None:
    def fake_request(request) -> dict:
        url = request.full_url
        if "oauth2.googleapis.com" in url:
            return {"access_token": "synthetic-access"}
        if "appDataFolder" in url:
            return {"files": []}
        if "/synthetic-folder?" in url:
            return {"mimeType": drive_probe.FOLDER_MIME}
        if "pageToken=second" in url:
            return {"files": [{"name": "second.md"}]}
        return {"files": [{"name": "first.md"}], "nextPageToken": "second"}

    monkeypatch.setattr(drive_probe, "_json_request", fake_request)
    assert drive_probe.check_drive(SETTINGS)["markdown_files"] == 2
