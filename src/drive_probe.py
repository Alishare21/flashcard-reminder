"""Check the flashcard OAuth client's Drive access without exposing content."""

from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from typing import Mapping

from dotenv import dotenv_values


DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
FOLDER_MIME = "application/vnd.google-apps.folder"


def _json_request(request: urllib.request.Request) -> dict:
    """Return a JSON response, leaving credentials out of logs."""
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def check_drive(settings: Mapping[str, str]) -> dict[str, int | bool | str]:
    """Refresh OAuth and return only Drive reachability and note-file counts."""
    required = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "GOOGLE_DRIVE_NOTES_FOLDER_ID")
    if not all(settings.get(key) for key in required):
        raise ValueError("Drive credentials or notes folder ID are missing")
    token_body = urllib.parse.urlencode(
        {
            "client_id": settings["GOOGLE_CLIENT_ID"],
            "client_secret": settings["GOOGLE_CLIENT_SECRET"],
            "refresh_token": settings["GOOGLE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }
    ).encode("ascii")
    token = _json_request(
        urllib.request.Request(
            TOKEN_ENDPOINT,
            data=token_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    )["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    app_data_query = urllib.parse.urlencode({"spaces": "appDataFolder", "pageSize": 1, "fields": "files(id)"})
    _json_request(urllib.request.Request(f"{DRIVE_FILES}?{app_data_query}", headers=headers))
    folder_id = settings["GOOGLE_DRIVE_NOTES_FOLDER_ID"]
    folder_query = urllib.parse.urlencode({"fields": "mimeType"})
    folder = _json_request(urllib.request.Request(f"{DRIVE_FILES}/{folder_id}?{folder_query}", headers=headers))
    if folder.get("mimeType") != FOLDER_MIME:
        raise ValueError("Saved Drive notes folder is not accessible")
    markdown_count = 0
    page_token = None
    while True:
        query = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "files(name),nextPageToken",
            "pageSize": 100,
        }
        if page_token:
            query["pageToken"] = page_token
        notes_query = urllib.parse.urlencode(query)
        notes = _json_request(urllib.request.Request(f"{DRIVE_FILES}?{notes_query}", headers=headers))
        markdown_count += sum(1 for item in notes.get("files", []) if item.get("name", "").lower().endswith(".md"))
        page_token = notes.get("nextPageToken")
        if not page_token:
            break
    return {"status": "passed", "app_data_reachable": True, "notes_folder_reachable": True, "markdown_files": markdown_count}


def main() -> int:
    """Print a count-only JSON result for a Trigger.dev Development task."""
    settings = dict(os.environ)
    local_env = Path(__file__).resolve().parents[1] / ".env"
    if local_env.exists():
        settings.update({key: value for key, value in dotenv_values(local_env).items() if value and key not in settings})
    try:
        result = check_drive(settings)
    except urllib.error.HTTPError as error:
        result = {"status": "failed", "http_status": error.code}
    except (urllib.error.URLError, KeyError, ValueError):
        result = {"status": "failed", "reason": "Drive access unavailable"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
