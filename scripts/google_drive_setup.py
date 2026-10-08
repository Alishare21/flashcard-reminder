"""Create a Drive folder owned by the flashcard OAuth app, without logging secrets."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import dotenv_values, set_key


FOLDER_NAME = "Flashcard Reminder - synced"
FOLDER_MIME = "application/vnd.google-apps.folder"
API = "https://www.googleapis.com/drive/v3/files"


def request_json(url: str, token: str | None = None, *, body: dict | None = None) -> dict:
    """Return a JSON response from a Google endpoint without logging headers."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=20) as response:
        return json.load(response)


def access_token(settings: dict[str, str | None]) -> str:
    """Exchange the saved refresh token for a short-lived access token."""
    payload = urllib.parse.urlencode(
        {
            "client_id": settings["GOOGLE_CLIENT_ID"],
            "client_secret": settings["GOOGLE_CLIENT_SECRET"],
            "refresh_token": settings["GOOGLE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }
    ).encode("ascii")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)["access_token"]


def ensure_folder(token: str, stored_id: str | None) -> str:
    """Find or create the one app-owned notes folder; return its Drive ID."""
    if stored_id:
        query = urllib.parse.urlencode({"fields": "id,mimeType", "supportsAllDrives": "false"})
        found = request_json(f"{API}/{stored_id}?{query}", token)
        if found.get("mimeType") != FOLDER_MIME:
            raise ValueError("Saved Drive folder ID does not identify a folder.")
        return stored_id

    clause = f"name = '{FOLDER_NAME}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    query = urllib.parse.urlencode({"q": clause, "spaces": "drive", "fields": "files(id,name,mimeType)", "pageSize": "100"})
    matches = request_json(f"{API}?{query}", token).get("files", [])
    if matches:
        return matches[0]["id"]

    query = urllib.parse.urlencode({"fields": "id,name,mimeType"})
    created = request_json(
        f"{API}?{query}",
        token,
        body={"name": FOLDER_NAME, "mimeType": FOLDER_MIME},
    )
    if created.get("mimeType") != FOLDER_MIME or not created.get("id"):
        raise ValueError("Google did not confirm folder creation.")
    return created["id"]


def main() -> int:
    """Persist the app-owned folder ID in the gitignored local .env file."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    settings = dotenv_values(env_path)
    if not all(settings.get(key) for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")):
        print("Google OAuth settings are incomplete in .env.")
        return 1
    try:
        folder_id = ensure_folder(access_token(settings), settings.get("GOOGLE_DRIVE_NOTES_FOLDER_ID"))
    except urllib.error.HTTPError as error:
        print(f"Google Drive folder setup failed (HTTP {error.code}).")
        return 1
    except (urllib.error.URLError, KeyError, ValueError):
        print("Google Drive folder setup failed before confirmation.")
        return 1
    set_key(str(env_path), "GOOGLE_DRIVE_NOTES_FOLDER_ID", folder_id)
    print(f"App-owned notes folder: https://drive.google.com/drive/folders/{folder_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
