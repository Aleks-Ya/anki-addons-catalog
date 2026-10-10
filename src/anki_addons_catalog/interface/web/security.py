import hashlib
import hmac
import logging
import secrets
import time

import httpx
from starlette.requests import Request

log = logging.getLogger(__name__)

PASS_COOKIE = "ai_pass"
SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def client_ip(request: Request) -> str:
    """The visitor's address: the first X-Forwarded-For entry set by the HuggingFace proxy, else the peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class HumanCheck:
    """Cloudflare Turnstile verification plus a signed, short-lived cookie that marks a verified visitor.

    Without a Turnstile secret the check is disabled (local development).
    """

    def __init__(self, site_key: str | None, secret: str | None, session_secret: str | None,
                 pass_ttl_seconds: int) -> None:
        self.site_key = site_key if secret else None
        self._secret = secret
        self._key = (session_secret or secrets.token_hex(32)).encode()
        self._ttl = pass_ttl_seconds

    @property
    def enabled(self) -> bool:
        return self._secret is not None

    def _sign(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()

    def issue_pass(self, now: float | None = None) -> str:
        expires = str(int((now or time.time()) + self._ttl))
        return f"{expires}.{self._sign(expires)}"

    def has_pass(self, request: Request, now: float | None = None) -> bool:
        if not self.enabled:
            return True
        value = request.cookies.get(PASS_COOKIE, "")
        expires, _, signature = value.partition(".")
        if not expires.isdigit() or not hmac.compare_digest(signature, self._sign(expires)):
            return False
        return int(expires) > (now or time.time())

    async def verify(self, token: str, ip: str) -> bool:
        if not self.enabled:
            return True
        if not token:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                response = await http.post(SITEVERIFY_URL, data={
                    "secret": self._secret, "response": token, "remoteip": ip})
            return bool(response.json().get("success"))
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Turnstile verification failed: %s", e)
            return False

    @property
    def ttl_seconds(self) -> int:
        return self._ttl
