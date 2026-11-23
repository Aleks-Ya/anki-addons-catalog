import hashlib
import hmac
import logging
import secrets
import time
import uuid

import httpx
from starlette.requests import Request

log = logging.getLogger(__name__)

PASS_COOKIE = "ai_pass"
SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
SITEVERIFY_TIMEOUT_SECONDS = 10
SITEVERIFY_ATTEMPTS = 2


def client_ip(request: Request) -> str:
    """The visitor's address: the first X-Forwarded-For entry set by the HuggingFace proxy, else the peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class HumanCheck:
    """Cloudflare Turnstile verification plus a signed, short-lived cookie that marks a verified visitor.

    The cookie is `<expires>.<nonce>.<signature>`; `<expires>.<nonce>` identifies the pass, so the rate limit can count
    questions per pass as well as per IP. Without a Turnstile secret the check is disabled (local development).
    """

    def __init__(self, site_key: str | None, secret: str | None, session_secret: str | None,
                 pass_ttl_seconds: int, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.site_key = site_key if secret else None
        self._secret = secret
        self._transport = transport  # for tests
        self._key = (session_secret or secrets.token_hex(32)).encode()
        self._ttl = pass_ttl_seconds

    @property
    def enabled(self) -> bool:
        return self._secret is not None

    def _sign(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()

    def issue_pass(self, now: float | None = None) -> str:
        payload = f"{int((now or time.time()) + self._ttl)}.{secrets.token_hex(8)}"
        return f"{payload}.{self._sign(payload)}"

    def pass_id(self, request: Request, now: float | None = None) -> str | None:
        """The id of the visitor's valid, unexpired pass; None without one or with the check disabled."""
        if not self.enabled:
            return None
        payload, _, signature = request.cookies.get(PASS_COOKIE, "").rpartition(".")
        expires, _, nonce = payload.partition(".")
        if not expires.isdigit() or not nonce or not hmac.compare_digest(signature, self._sign(payload)):
            return None
        return payload if int(expires) > (now or time.time()) else None

    def has_pass(self, request: Request, now: float | None = None) -> bool:
        return not self.enabled or self.pass_id(request, now) is not None

    async def verify(self, token: str, ip: str) -> bool:
        """Ask Cloudflare whether the widget's token is valid. A network error is retried once with the same
        idempotency key, so Cloudflare does not reject the retry as a reused token. Every failure is logged with
        what Cloudflare answered, or the exception type (httpx timeouts have an empty message)."""
        if not self.enabled:
            return True
        if not token:
            return False
        data = {"secret": self._secret, "response": token, "remoteip": ip, "idempotency_key": str(uuid.uuid4())}
        async with httpx.AsyncClient(timeout=SITEVERIFY_TIMEOUT_SECONDS, transport=self._transport) as http:
            for attempt in range(1, SITEVERIFY_ATTEMPTS + 1):
                started = time.monotonic()
                try:
                    response = await http.post(SITEVERIFY_URL, data=data)
                    break
                except httpx.RequestError as e:
                    log.warning("Turnstile siteverify failed after %.1f s (attempt %d of %d): %r",
                                time.monotonic() - started, attempt, SITEVERIFY_ATTEMPTS, e)
            else:
                return False
        try:
            result = response.json()
        except ValueError:
            result = None
        if response.status_code != 200 or not isinstance(result, dict):
            log.warning("Turnstile siteverify answered HTTP %d: %s", response.status_code, response.text[:200])
            return False
        if not result.get("success"):
            log.warning("Turnstile siteverify rejected the token: error-codes %s, hostname %s",
                        result.get("error-codes"), result.get("hostname"))
            return False
        return True

    @property
    def ttl_seconds(self) -> int:
        return self._ttl
