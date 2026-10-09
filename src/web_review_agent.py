"""Serve a private local browser interface for reviewing due flashcards."""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import webbrowser

from src.config_agent import SchedulingSettings, Settings
from src.review_agent import save_review
from src.scheduler_agent import DueSummary, get_due_cards


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/google-sync.js": ("google-sync.js", "text/javascript; charset=utf-8"),
    "/google-config.js": ("google-config.js", "text/javascript; charset=utf-8"),
}


def _card_dict(card: Any) -> dict[str, object]:
    """Convert one selected card into a JSON-safe local-browser record."""

    return {
        "id": card.id,
        "deck": card.deck,
        "type": card.type,
        "front": card.front,
        "back": card.back,
        "due_date": card.due_date,
        "is_new": card.is_new,
    }


def _summary_payload(summary: DueSummary, limit: int | None = None) -> dict[str, object]:
    cards = summary.cards[:limit] if limit is not None else summary.cards
    return {
        "cards": [_card_dict(card) for card in cards],
        "total": len(cards),
        "available_total": summary.total,
        "new_count": sum(1 for card in cards if card.is_new),
        "review_count": sum(1 for card in cards if not card.is_new),
        "capped_review_count": summary.capped_review_count,
        "oldest_overdue_days": summary.oldest_overdue_days,
        "decks": [{"name": deck, "count": count} for deck, count in summary.by_deck],
    }


def build_session_payload(
    db_path: str | Path,
    today: str,
    settings: Settings | SchedulingSettings,
    deck: str | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    """Return due-card data for the local visual review session."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    payload = _summary_payload(get_due_cards(db_path, today, settings, deck), limit)
    payload["today"] = today
    return payload


def submit_review(
    db_path: str | Path,
    today: str,
    settings: Settings | SchedulingSettings,
    card_id: str,
    grade: int,
    deck: str | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    """Validate and save one due-card answer, then return the refreshed session."""

    if grade not in {1, 2, 3, 4}:
        raise ValueError("grade must be 1, 2, 3, or 4")
    due = get_due_cards(db_path, today, settings, deck)
    if card_id not in {card.id for card in due.cards}:
        raise ValueError("card is no longer due")
    save_review(db_path, card_id, grade, today, settings)
    return build_session_payload(db_path, today, settings, deck, limit)


def _handler_class(
    db_path: Path,
    today: str,
    settings: Settings | SchedulingSettings,
    after_review: Callable[[], str] | None,
) -> type[BaseHTTPRequestHandler]:
    """Create an HTTP handler bound to one review session configuration."""

    class ReviewHandler(BaseHTTPRequestHandler):
        server_version = "FlashcardReview/1.0"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _headers(self, status: HTTPStatus, content_type: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self' https://accounts.google.com; connect-src 'self' https://www.googleapis.com https://tasks.googleapis.com; frame-src https://accounts.google.com; frame-ancestors 'none'",
            )
            self.end_headers()

        def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(data))
            self.wfile.write(data)

        def _is_local_request(self) -> bool:
            """Reject DNS rebinding and cross-origin browser writes."""

            host = self.headers.get("Host", "").split(":", 1)[0].lower()
            return host in {"127.0.0.1", "localhost"}

        def _session_options(self, query: dict[str, list[str]]) -> tuple[str | None, int | None]:
            deck = query.get("deck", [""])[0].strip() or None
            raw_limit = query.get("limit", [""])[0].strip()
            limit = int(raw_limit) if raw_limit else None
            return deck, limit

        def do_GET(self) -> None:
            if not self._is_local_request():
                self._json(HTTPStatus.FORBIDDEN, {"error": "local access only"})
                return
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
                return
            if parsed.path == "/api/session":
                try:
                    deck, limit = self._session_options(parse_qs(parsed.query))
                    self._json(HTTPStatus.OK, build_session_payload(db_path, today, settings, deck, limit))
                except (TypeError, ValueError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            static = STATIC_FILES.get(parsed.path)
            if static is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            filename, content_type = static
            try:
                data = (WEB_ROOT / filename).read_bytes()
            except OSError:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "interface unavailable"})
                return
            self._headers(HTTPStatus.OK, content_type, len(data))
            self.wfile.write(data)

        def do_POST(self) -> None:
            if not self._is_local_request():
                self._json(HTTPStatus.FORBIDDEN, {"error": "local access only"})
                return
            if urlparse(self.path).path != "/api/review":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    raise ValueError("content type must be application/json")
                origin = self.headers.get("Origin")
                if origin is not None and origin != f"http://{self.headers.get('Host', '')}":
                    raise ValueError("cross-origin request rejected")
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 4096:
                    raise ValueError("invalid request size")
                raw = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("request must be an object")
                card_id = str(raw.get("card_id", "")).strip()
                grade = int(raw.get("grade", 0))
                deck = str(raw.get("deck", "")).strip() or None
                raw_limit = raw.get("limit")
                limit = int(raw_limit) if raw_limit is not None else None
                if not card_id:
                    raise ValueError("card_id is required")
                session = submit_review(db_path, today, settings, card_id, grade, deck, limit)
                cloud = after_review() if after_review is not None else "disabled"
                self._json(HTTPStatus.OK, {"session": session, "cloud": cloud})
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    return ReviewHandler


def run_web_app(
    db_path: str | Path,
    today: str,
    settings: Settings | SchedulingSettings,
    port: int = 8765,
    open_browser: bool = True,
    after_review: Callable[[], str] | None = None,
) -> None:
    """Run the local-only visual review server until interrupted."""

    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    handler = _handler_class(Path(db_path), today, settings, after_review)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
