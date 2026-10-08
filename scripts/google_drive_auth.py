"""Authorize this personal Drive client and verify its limited API access.

Run this interactively on the user's computer. Tokens are written only to the
gitignored .env file; no OAuth code, token, or client secret is printed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dotenv import dotenv_values, set_key


SCOPES = (
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.appdata",
)
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DRIVE_ENDPOINT = "https://www.googleapis.com/drive/v3/files"
KNOWN_FOLDER_ID = "1l6qDS8vLBv9G-ifGfVXyH0SEiaxoWBS0"


def _challenge(verifier: str) -> str:
    """Return the unpadded SHA-256 PKCE challenge for a verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _request_json(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict:
    """Send an HTTPS request and decode its JSON response."""
    request = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def _oauth_error_name(error: urllib.error.HTTPError) -> str:
    """Return only a known OAuth error identifier, never response details."""
    try:
        name = json.load(error).get("error")
    except (ValueError, OSError):
        return "unknown"
    if name in {"invalid_client", "invalid_grant", "invalid_request", "unauthorized_client"}:
        return name
    return "unknown"


def _check_drive(access_token: str) -> tuple[bool, bool]:
    """Check app data access and whether the existing notes folder is visible."""
    headers = {"Authorization": f"Bearer {access_token}"}
    query = urllib.parse.urlencode({"spaces": "appDataFolder", "pageSize": 1, "fields": "files(id)"})
    _request_json(f"{DRIVE_ENDPOINT}?{query}", headers=headers)
    folder_url = f"{DRIVE_ENDPOINT}/{KNOWN_FOLDER_ID}?fields=id,mimeType"
    try:
        _request_json(folder_url, headers=headers)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return True, False
        raise
    return True, True


def _callback_values(url: str, state: str, port: int) -> dict[str, str]:
    """Validate a loopback callback URL copied from an external browser."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != port:
        return {"error": "The callback URL does not match this authorization session."}
    parameters = urllib.parse.parse_qs(parsed.query)
    if parameters.get("state", [""])[0] != state:
        return {"error": "The callback state does not match this authorization session."}
    if parameters.get("error"):
        return {"error": "Google authorization was declined or blocked."}
    code = parameters.get("code", [""])[0]
    if not code:
        return {"error": "The callback URL has no authorization code."}
    return {"code": code}


def main() -> int:
    """Run desktop OAuth with PKCE or recheck an existing Drive grant."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Test a saved refresh token without consent")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    values = dotenv_values(env_path)
    client_id = values.get("GOOGLE_CLIENT_ID")
    client_secret = values.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Google OAuth client settings are missing from .env.")
        return 1

    if args.check:
        refresh_token = values.get("GOOGLE_REFRESH_TOKEN")
        if not refresh_token:
            print("No Google refresh token is saved in .env.")
            return 1
        payload = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("ascii")
        try:
            tokens = _request_json(
                TOKEN_ENDPOINT,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            app_data_ok, folder_visible = _check_drive(tokens["access_token"])
        except urllib.error.HTTPError as error:
            print(f"Google access check failed (HTTP {error.code}, {_oauth_error_name(error)}).")
            return 1
        except (urllib.error.URLError, KeyError, ValueError):
            print("Google access check failed before Drive responded.")
            return 1
        print(f"Drive private app data: {'reachable' if app_data_ok else 'unreachable'}")
        print(f"Existing Flashcard Reminder folder: {'visible' if folder_visible else 'not accessible with limited scope'}")
        return 0

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    received: dict[str, str] = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            parameters = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if parameters.get("state", [""])[0] != state:
                self.send_error(400, "State mismatch")
                return
            if parameters.get("error"):
                received["error"] = "Google authorization was declined or blocked."
            else:
                received["code"] = parameters.get("code", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"You can return to the flashcard setup window.")

    callback_path = project_root / ".secrets" / "google-oauth-callback.txt"
    if callback_path.exists() and callback_path.stat().st_size:
        print("Remove the old OAuth callback file before starting a new session.")
        return 1

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect_uri = f"http://127.0.0.1:{server.server_port}/"
        parameters = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
            "state": state,
        }
        url = f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(parameters)}"
        print("Paste this one-time consent link into Brave:")
        print(url)
        deadline = time.monotonic() + 600
        while not received and time.monotonic() < deadline:
            server.handle_request()
            if callback_path.exists() and callback_path.stat().st_size:
                copied_url = callback_path.read_text(encoding="utf-8").strip()
                callback_path.unlink()
                received.update(_callback_values(copied_url, state, server.server_port))

    if not received.get("code"):
        print(received.get("error", "Google authorization did not complete within ten minutes."))
        return 1

    payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": received["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("ascii")
    try:
        tokens = _request_json(
            TOKEN_ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]
    except urllib.error.HTTPError as error:
        print(f"Google token exchange failed (HTTP {error.code}, {_oauth_error_name(error)}).")
        return 1
    except (urllib.error.URLError, KeyError, ValueError):
        print("Google token exchange failed before Drive responded.")
        return 1

    set_key(str(env_path), "GOOGLE_REFRESH_TOKEN", refresh_token)
    print("Refresh token saved to .env.")
    try:
        app_data_ok, folder_visible = _check_drive(access_token)
    except urllib.error.HTTPError as error:
        print(f"Drive API check failed (HTTP {error.code}).")
        return 1
    except (urllib.error.URLError, KeyError, ValueError):
        print("Drive API check failed before a valid response was received.")
        return 1
    print(f"Drive private app data: {'reachable' if app_data_ok else 'unreachable'}")
    print(f"Existing Flashcard Reminder folder: {'visible' if folder_visible else 'not accessible with limited scope'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
