"""HMAC-signed policy tokens. policy-mcp issues them; action MCPs verify locally, no network call."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from pydantic import BaseModel

from menara_core.errors import TokenError

DEFAULT_TTL_S = 300


class PolicyToken(BaseModel):
    action: str
    target: str
    approved_by: str
    issued_at: int
    expires_at: int
    nonce: str


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(key: bytes, payload: str) -> str:
    return _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())


def issue_token(
    key: bytes,
    *,
    action: str,
    target: str,
    approved_by: str,
    ttl_s: int = DEFAULT_TTL_S,
    now: int | None = None,
) -> str:
    issued = int(time.time()) if now is None else now
    token = PolicyToken(
        action=action,
        target=target,
        approved_by=approved_by,
        issued_at=issued,
        expires_at=issued + ttl_s,
        nonce=secrets.token_hex(8),
    )
    payload = _b64(json.dumps(token.model_dump(), sort_keys=True, separators=(",", ":")).encode())
    return f"{payload}.{_sign(key, payload)}"


def verify_token(
    key: bytes, token: str, *, action: str, target: str, now: int | None = None
) -> PolicyToken:
    try:
        payload, signature = token.split(".")
    except ValueError as exc:
        raise TokenError("Malformed policy token") from exc
    if not hmac.compare_digest(signature, _sign(key, payload)):
        raise TokenError("Policy token signature is invalid")
    try:
        parsed = PolicyToken.model_validate(json.loads(_unb64(payload)))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenError("Policy token payload is unreadable") from exc
    current = int(time.time()) if now is None else now
    if current >= parsed.expires_at:
        raise TokenError("Policy token has expired")
    if parsed.action != action or parsed.target != target:
        raise TokenError("Policy token was issued for a different action or target")
    return parsed
