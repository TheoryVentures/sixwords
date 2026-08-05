"""Publishing layer for sixwordidea.com.

Published ideas live in a Supabase table; this module wraps the two Supabase
APIs the CLI needs: email one-time-code sign-in (GoTrue) and the ``ideas``
table (PostgREST). Sessions are cached at ``~/.sixwords/credentials.json``
and refreshed automatically when the access token expires.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

# Filled in for the canonical deployment; both are public values (the anon
# key is safe to ship — writes require a signed-in user via row-level
# security). Override with the environment variables of the same name.
DEFAULT_SUPABASE_URL = "https://xqdndnfrmrwjpfcrcvvb.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = "sb_publishable_nePcMb7ZUOaJX4EP6EmEnA_mOWgZ7ac"

SITE_BASE_URL = "https://sixwordidea.com"
DEFAULT_CREDENTIALS_PATH = Path.home() / ".sixwords" / "credentials.json"

IDEA_COLUMNS = "slug,title,story,doc,published_at"


class PublishError(Exception):
    """A publishing operation could not be completed."""


class SupabaseClient:
    """Minimal client for the sixwordidea.com Supabase backend."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        anon_key: str | None = None,
        credentials_path: Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        base_url = base_url or os.environ.get("SIXWORDS_SUPABASE_URL") or DEFAULT_SUPABASE_URL
        anon_key = (
            anon_key or os.environ.get("SIXWORDS_SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_ANON_KEY
        )
        if not base_url or not anon_key:
            raise PublishError(
                "Publishing is not configured: set SIXWORDS_SUPABASE_URL and "
                "SIXWORDS_SUPABASE_ANON_KEY (see supabase/README.md)."
            )
        self.credentials_path = credentials_path or DEFAULT_CREDENTIALS_PATH
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"apikey": anon_key},
            timeout=30.0,
            transport=transport,
        )

    # -- auth -------------------------------------------------------------

    def request_code(self, email: str) -> None:
        """Email *email* a one-time sign-in code."""
        response = self._http.post(
            "/auth/v1/otp",
            json={"email": email, "create_user": True},
        )
        _ensure_ok(response, "Could not send a sign-in code")

    def verify_code(self, email: str, code_or_link: str) -> str:
        """Exchange a one-time code (or pasted sign-in link) for a session.

        Caches the session and returns the email. Sign-in emails carry a
        link unless the project has a custom SMTP provider with a code
        template, so both forms are accepted.
        """
        if code_or_link.startswith(("http://", "https://")):
            parsed = urlparse(code_or_link)
            fragment = parse_qs(parsed.fragment)
            if "access_token" in fragment:
                # The link was already clicked: the browser landed on a page
                # with the session tokens in the URL fragment. Save them.
                self._save_session(
                    email,
                    {
                        "access_token": fragment["access_token"][0],
                        "refresh_token": fragment["refresh_token"][0],
                        "expires_at": int(fragment["expires_at"][0])
                        if "expires_at" in fragment
                        else None,
                    },
                )
                return email
            token_hash = parse_qs(parsed.query).get("token", [None])[0]
            if not token_hash:
                raise PublishError("That link has no sign-in token; paste the full email link.")
            payload = {"type": "magiclink", "token_hash": token_hash}
        else:
            payload = {"type": "email", "email": email, "token": code_or_link}
        response = self._http.post("/auth/v1/verify", json=payload)
        _ensure_ok(response, "Sign-in failed")
        self._save_session(email, response.json())
        return email

    def signed_in_email(self) -> str | None:
        session = self._load_session()
        return session["email"] if session else None

    def _access_token(self) -> str:
        session = self._load_session()
        if session is None:
            raise PublishError("Not signed in. Run: sixwords login")
        if session["expires_at"] > time.time() + 30:
            return session["access_token"]
        response = self._http.post(
            "/auth/v1/token",
            params={"grant_type": "refresh_token"},
            json={"refresh_token": session["refresh_token"]},
        )
        if response.is_error:
            raise PublishError("Your session has expired. Run: sixwords login")
        self._save_session(session["email"], response.json())
        return self._load_session()["access_token"]

    def _load_session(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.credentials_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _save_session(self, email: str, grant: dict[str, Any]) -> None:
        session = {
            "email": email,
            "access_token": grant["access_token"],
            "refresh_token": grant["refresh_token"],
            "expires_at": grant.get("expires_at") or time.time() + grant.get("expires_in", 3600),
        }
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials_path.write_text(json.dumps(session, indent=2), encoding="utf-8")
        self.credentials_path.chmod(0o600)

    # -- ideas ------------------------------------------------------------

    def publish(self, *, slug: str, title: str, story: str, doc: dict[str, Any]) -> str:
        """Insert a published idea. Returns its public URL."""
        response = self._http.post(
            "/rest/v1/ideas",
            headers={"Authorization": f"Bearer {self._access_token()}"},
            json={"slug": slug, "title": title, "story": story, "doc": doc},
        )
        if response.status_code == 409:
            raise PublishError(
                f'An idea with slug "{slug}" is already published; retitle the story to publish.'
            )
        if response.status_code in (401, 403):
            raise PublishError("Publishing was rejected. Run: sixwords login")
        _ensure_ok(response, "Publishing failed")
        return f"{SITE_BASE_URL}/ideas/{slug}.json"

    def list_ideas(self) -> list[dict[str, Any]]:
        """All published ideas, newest first."""
        response = self._http.get(
            "/rest/v1/ideas",
            params={"select": IDEA_COLUMNS, "order": "published_at.desc"},
        )
        _ensure_ok(response, "Could not fetch published ideas")
        return response.json()


def _ensure_ok(response: httpx.Response, context: str) -> None:
    if not response.is_error:
        return
    try:
        detail = response.json()
        message = detail.get("msg") or detail.get("message") or detail.get("error_description")
    except json.JSONDecodeError:
        message = None
    raise PublishError(f"{context}: {message or response.text or response.status_code}")
