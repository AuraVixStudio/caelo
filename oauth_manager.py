"""xAI Grok OAuth (SuperGrok / X Premium+) — logowanie przez konto zamiast klucza API.

Odwzorowuje przepływ używany przez grok-cli / Hermes Agent:
  - OAuth 2.0 Authorization Code + PKCE (S256)
  - lokalny serwer callback na 127.0.0.1 (loopback), z fallbackiem na wolny port
  - token Bearer jest wysyłany WYŁĄCZNIE do https://api.x.ai

Endpointy potwierdzone z https://auth.x.ai/.well-known/openid-configuration.
"""

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from config import (
    OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL,
    OAUTH_USERINFO_URL,
    OAUTH_CLIENT_ID,
    OAUTH_SCOPES,
    OAUTH_REDIRECT_PORT,
    OAUTH_REDIRECT_PATH,
    AUTH_FILE,
    atomic_write_text,
    load_json_or_backup,
)

log = logging.getLogger(__name__)

# Bezpieczeństwo: token wolno wysyłać tylko do tego hosta.
API_HOST = "https://api.x.ai"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _gen_pkce():
    """Zwraca (code_verifier, code_challenge) wg PKCE/S256."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    """Łapie jednorazowe przekierowanie z serwera autoryzacji xAI."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != OAUTH_REDIRECT_PATH:
            # np. /favicon.ico — ignorujemy, czekamy dalej na właściwy callback
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        self.server.oauth_result = {
            "code": params.get("code", [None])[0],
            "state": params.get("state", [None])[0],
            "error": params.get("error", [None])[0],
            "error_description": params.get("error_description", [None])[0],
        }

        ok = self.server.oauth_result.get("code") is not None
        msg = (
            "Sign-in complete — you can close this tab and return to the app."
            if ok else
            "Sign-in failed. Return to the app and try again."
        )
        body = (
            "<html><head><meta charset='utf-8'></head>"
            "<body style='font-family:sans-serif;background:#0f1323;color:#fff;"
            "text-align:center;padding-top:80px'>"
            f"<h2>{msg}</h2></body></html>"
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # cisza w konsoli


class OAuthManager:
    """Zarządza logowaniem OAuth, przechowywaniem i odświeżaniem tokenów."""

    def __init__(self):
        self.tokens = {}
        self._lock = threading.Lock()
        self._load()

    # --- trwałość ---
    def _load(self):
        # P1-11: korupcja → backup .corrupt + pusty (nie kasuj tokenów po cichu).
        self.tokens = load_json_or_backup(AUTH_FILE, {}) or {}

    def _save(self):
        # P1-11: zapis ATOMOWY (temp + os.replace) — crash w trakcie nie zostawi
        # uszkodzonego pliku z tokenami (był prosty write_text z połykaniem błędu).
        try:
            atomic_write_text(AUTH_FILE, json.dumps(self.tokens, indent=2))
        except Exception:
            log.warning("Failed to save %s", AUTH_FILE.name, exc_info=True)

    # --- stan ---
    def is_authenticated(self) -> bool:
        return bool(self.tokens.get("refresh_token") or self.tokens.get("access_token"))

    def get_account(self) -> dict:
        return self.tokens.get("account") or {}

    def logout(self):
        self.tokens = {}
        try:
            if AUTH_FILE.exists():
                AUTH_FILE.unlink()
        except Exception:
            pass

    # --- przepływ logowania (blokujący — uruchamiać w wątku tła) ---
    def login(self, status_cb=None, timeout=300):
        """Pełny przepływ PKCE. Zwraca dict konta przy sukcesie, rzuca wyjątek przy błędzie."""
        def report(msg):
            if status_cb:
                try:
                    status_cb(msg)
                except Exception:
                    pass

        verifier, challenge = _gen_pkce()
        state = secrets.token_hex(16)
        nonce = secrets.token_hex(16)

        server, port = self._start_server()
        redirect_uri = f"http://127.0.0.1:{port}{OAUTH_REDIRECT_PATH}"

        params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": OAUTH_SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "nonce": nonce,
            "plan": "generic",
            "referrer": "grok-desktop-app",
        }
        url = OAUTH_AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

        report("Opening browser...")
        print(f"[OAuth] Open in your browser if it doesn't open automatically:\n{url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass

        try:
            result = self._wait_for_callback(server, timeout=timeout)
        finally:
            try:
                server.server_close()
            except Exception:
                pass

        if not result:
            raise RuntimeError("Timed out waiting for sign-in confirmation.")
        if result.get("error"):
            raise RuntimeError(
                f"xAI server rejected the sign-in: "
                f"{result.get('error_description') or result.get('error')}"
            )
        if result.get("state") != state:
            raise RuntimeError("State parameter mismatch — aborted (possible CSRF).")
        code = result.get("code")
        if not code:
            raise RuntimeError("No authorization code received.")

        report("Exchanging code for token...")
        self._exchange_code(code, redirect_uri, verifier)
        report("Fetching account info...")
        self._fetch_userinfo()
        return self.get_account()

    def _start_server(self):
        last_err = None
        for port in (OAUTH_REDIRECT_PORT, 0):  # preferowany port, potem dowolny wolny
            try:
                server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
                server.oauth_result = None
                return server, server.server_address[1]
            except OSError as e:
                last_err = e
        raise RuntimeError(f"Cannot start local callback server: {last_err}")

    @staticmethod
    def _wait_for_callback(server, timeout=300):
        server.timeout = 1  # handle_request wraca po 1 s bez żądania
        deadline = time.time() + timeout
        while time.time() < deadline:
            server.handle_request()
            if server.oauth_result is not None:
                return server.oauth_result
        return None

    # --- tokeny ---
    def _exchange_code(self, code, redirect_uri, verifier):
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": OAUTH_CLIENT_ID,
            "code_verifier": verifier,
        }
        r = requests.post(
            OAUTH_TOKEN_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Token exchange failed ({r.status_code}): {r.text[:300]}")
        self._store_token_response(r.json())

    def _refresh(self):
        rt = self.tokens.get("refresh_token")
        if not rt:
            raise RuntimeError("No refresh_token — please sign in again.")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": OAUTH_CLIENT_ID,
        }
        r = requests.post(
            OAUTH_TOKEN_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Token refresh failed ({r.status_code}).")
        self._store_token_response(r.json())

    def _store_token_response(self, resp):
        access = resp.get("access_token")
        if not access:
            raise RuntimeError("No access_token in server response.")
        self.tokens["access_token"] = access
        if resp.get("refresh_token"):
            self.tokens["refresh_token"] = resp["refresh_token"]
        self.tokens["token_type"] = resp.get("token_type", "Bearer")
        self.tokens["scope"] = resp.get("scope", OAUTH_SCOPES)
        if resp.get("id_token"):
            self.tokens["id_token"] = resp["id_token"]
        expires_in = resp.get("expires_in")
        if expires_in:
            # 60 s zapasu przed faktycznym wygaśnięciem
            self.tokens["expires_at"] = int(time.time()) + int(expires_in) - 60
        else:
            self.tokens.pop("expires_at", None)
        self._save()

    def _fetch_userinfo(self):
        token = self.tokens.get("access_token")
        if not token:
            return
        try:
            r = requests.get(
                OAUTH_USERINFO_URL,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=20,
            )
            if r.status_code == 200:
                self.tokens["account"] = r.json()
                self._save()
        except Exception:
            pass

    def get_access_token(self):
        """Zwraca ważny access_token (odświeża, jeśli wygasł) lub None, gdy brak logowania."""
        if not (self.tokens.get("access_token") or self.tokens.get("refresh_token")):
            return None
        with self._lock:
            exp = self.tokens.get("expires_at")
            if exp and time.time() >= exp:
                try:
                    self._refresh()
                except Exception:
                    return None
            return self.tokens.get("access_token")
