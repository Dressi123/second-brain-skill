"""Single-user OAuth 2.1, with nothing to store.

The Mac version kept clients and live tokens in a JSON file next to the
process. A serverless function has no such file: every request may land on a
fresh instance, and a token store that vanishes would log the user out
constantly.

So nothing is stored. Every credential -- the client registration, the
authorization code, the access and refresh tokens -- is a self-describing
blob signed with one server secret. Validation is a signature check plus an
expiry check, needing no lookup at all.

Two consequences worth being explicit about:

1. No refresh-token revocation list. A refresh token stays valid until it
   expires rather than being revocable, and rotation cannot be enforced.
   Rotating OAUTH_SIGNING_SECRET invalidates everything at once, which is the
   recovery path if a token is ever exposed.
2. Authorization codes cannot be marked spent across instances. They are
   PKCE-bound (S256 required, so a stolen code is useless without the
   verifier), live 120 seconds, and are recorded as spent on the instance
   that redeemed them -- which catches the ordinary case, since the exchange
   happens seconds later on the same warm instance.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path

SECRET = os.environ.get("OAUTH_SIGNING_SECRET", "")
PASSWORD = os.environ.get("MCP_APPROVAL_PASSWORD", "")

ACCESS_TOKEN_TTL = 60 * 60          # 1 hour; Claude refreshes ahead of expiry
REFRESH_TOKEN_TTL = 60 * 60 * 24 * 90
AUTH_CODE_TTL = 120                 # short, because it cannot be revoked

SPENT_CODES = Path("/tmp/spent-auth-codes")


def _b64(raw: bytes) -> str:
    return urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(kind: str, payload: dict, ttl: int | None) -> str:
    """Pack a payload plus its kind and expiry into one signed, opaque string."""
    body = dict(payload, kind=kind, iat=int(time.time()))
    if ttl is not None:
        body["exp"] = body["iat"] + ttl
    body["jti"] = secrets.token_urlsafe(9)
    encoded = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{mac}"


def verify(kind: str, token: str) -> dict | None:
    """Return the payload if the signature, kind and expiry all hold."""
    if not token or not SECRET or "." not in token:
        return None
    encoded, _, mac = token.rpartition(".")
    expected = hmac.new(SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        payload = json.loads(_unb64(encoded))
    except (ValueError, TypeError):
        return None
    if payload.get("kind") != kind:
        return None
    if "exp" in payload and payload["exp"] < int(time.time()):
        return None
    return payload


# -- clients: the registration IS the client_id ------------------------------

def register_client(redirect_uris: list[str], client_name: str) -> str:
    return sign("client", {"redirect_uris": redirect_uris, "client_name": client_name}, None)


def get_client(client_id: str) -> dict | None:
    return verify("client", client_id)


# -- authorization codes -----------------------------------------------------

def create_auth_code(client_id: str, redirect_uri: str, challenge: str, method: str) -> str:
    return sign("code", {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": method,
    }, AUTH_CODE_TTL)


def consume_auth_code(code: str) -> dict | None:
    payload = verify("code", code)
    if payload is None:
        return None
    if _already_spent(payload["jti"]):
        return None
    return payload


def _already_spent(jti: str) -> bool:
    """Best-effort replay check, scoped to this instance (see module docstring)."""
    try:
        now = int(time.time())
        seen = {}
        if SPENT_CODES.exists():
            seen = {
                k: v for k, v in json.loads(SPENT_CODES.read_text()).items()
                if v > now                      # drop entries past their code's expiry
            }
        if jti in seen:
            return True
        seen[jti] = now + AUTH_CODE_TTL
        SPENT_CODES.write_text(json.dumps(seen))
    except (OSError, ValueError):
        pass                                     # never block a real login on this
    return False


# -- tokens ------------------------------------------------------------------

def issue_tokens(client_id: str) -> tuple[str, str]:
    return (
        sign("access", {"client_id": client_id}, ACCESS_TOKEN_TTL),
        sign("refresh", {"client_id": client_id}, REFRESH_TOKEN_TTL),
    )


def rotate_refresh_token(old: str) -> tuple[str, str] | None:
    payload = verify("refresh", old)
    return issue_tokens(payload["client_id"]) if payload else None


def validate_access_token(token: str) -> bool:
    return verify("access", token) is not None


def verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    if method != "S256":
        return False
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return hmac.compare_digest(_b64(digest), code_challenge)


def check_password(supplied: str) -> bool:
    if not PASSWORD:
        return False
    return hmac.compare_digest(supplied or "", PASSWORD)
