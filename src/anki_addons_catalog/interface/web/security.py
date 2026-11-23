import asyncio
import hashlib
import hmac
import logging
import secrets
import socket
import time
import uuid
from collections.abc import Awaitable, Callable
from functools import partial

import httpx
from starlette.requests import Request

log = logging.getLogger(__name__)

PASS_COOKIE = "ai_pass"
SITEVERIFY_HOST = "challenges.cloudflare.com"
SITEVERIFY_URL = f"https://{SITEVERIFY_HOST}/turnstile/v0/siteverify"
SITEVERIFY_TIMEOUT_SECONDS = 10
SITEVERIFY_ATTEMPTS = 2

PROBE_TEST_SECRET = "1x0000000000000000000000000000000AA"  # Cloudflare's documented always-pass test secret
PROBE_CONTROL_URL = "https://www.cloudflare.com/"
PROBE_TIMEOUT_SECONDS = 5
PROBE_INTERVAL_SECONDS = 600
IPV4, IPV6 = "0.0.0.0", "::"  # local addresses that pick the IP version of a connection, not a server to bind


def family_transport(local_address: str) -> httpx.AsyncBaseTransport:
    """A transport that connects only over the IP version of `local_address`."""
    return httpx.AsyncHTTPTransport(local_address=local_address)


async def resolve(host: str) -> list[str]:
    """The addresses of `host`, in the order the resolver returns them, without duplicates."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


async def connect(address: str) -> None:
    """Open a TCP connection to port 443 of `address` and close it."""
    _, writer = await asyncio.open_connection(address, 443)
    writer.close()


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
                 pass_ttl_seconds: int, transport: httpx.AsyncBaseTransport | None = None,
                 family_transport: Callable[[str], httpx.AsyncBaseTransport] = family_transport) -> None:
        self.site_key = site_key if secret else None
        self._secret = secret
        self._transport = transport  # for tests
        self._family_transport = family_transport
        self._key = (session_secret or secrets.token_hex(32)).encode()
        self._ttl = pass_ttl_seconds
        self._probe_task: asyncio.Task[None] | None = None
        self._last_probe = float("-inf")

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
                self.start_probe()
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

    def start_probe(self) -> asyncio.Task[None] | None:
        """Run `probe` in the background: at startup and after a network error, at most once per
        PROBE_INTERVAL_SECONDS. None when the check is disabled or a probe ran recently."""
        now = time.monotonic()
        if not self.enabled or now - self._last_probe < PROBE_INTERVAL_SECONDS:
            return None
        self._last_probe = now
        self._probe_task = asyncio.create_task(self.probe())  # kept on self, so it is not garbage-collected
        return self._probe_task

    async def probe(self) -> None:
        """Log whether the app can reach Cloudflare siteverify: DNS, TCP to each address, HTTPS over IPv4, IPv6 and
        the default route, and another Cloudflare site. One `Turnstile probe:` line per check; it never raises.
        The HTTPS checks send Cloudflare's test secret, never the real one."""
        try:
            addresses = await asyncio.wait_for(resolve(SITEVERIFY_HOST), PROBE_TIMEOUT_SECONDS)
            log.info("Turnstile probe: DNS %s: %s", SITEVERIFY_HOST, ", ".join(addresses))
        except Exception as e:  # noqa: BLE001 - a diagnostic logs every error
            log.warning("Turnstile probe: DNS %s failed: %r", SITEVERIFY_HOST, e)
            addresses = []
        checks: list[tuple[str, Callable[[], Awaitable[str]]]] = [
            *((f"TCP {address}:443", partial(self._probe_tcp, address)) for address in addresses),
            ("HTTPS siteverify, default", partial(self._probe_siteverify, None)),
            ("HTTPS siteverify, IPv4", partial(self._probe_siteverify, IPV4)),
            ("HTTPS siteverify, IPv6", partial(self._probe_siteverify, IPV6)),
            (f"HTTPS {PROBE_CONTROL_URL}", self._probe_control),
        ]
        await asyncio.gather(*(self._timed(name, check) for name, check in checks))

    @staticmethod
    async def _timed(name: str, check: Callable[[], Awaitable[str]]) -> None:
        started = time.monotonic()
        try:
            detail = await asyncio.wait_for(check(), PROBE_TIMEOUT_SECONDS)
            log.info("Turnstile probe: %s ok in %.2f s%s", name, time.monotonic() - started, detail)
        except Exception as e:  # noqa: BLE001 - a diagnostic logs every error
            log.warning("Turnstile probe: %s failed after %.1f s: %r", name, time.monotonic() - started, e)

    @staticmethod
    async def _probe_tcp(address: str) -> str:
        await connect(address)
        return ""

    async def _probe_siteverify(self, local_address: str | None) -> str:
        """siteverify over the IP version of `local_address`, or the default route (the transport of `verify`)."""
        transport = self._family_transport(local_address) if local_address else self._transport
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS, transport=transport) as http:
            response = await http.post(SITEVERIFY_URL, data={"secret": PROBE_TEST_SECRET, "response": "probe"})
        return f": HTTP {response.status_code}, success {response.json().get('success')}"

    async def _probe_control(self) -> str:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS, transport=self._transport) as http:
            response = await http.head(PROBE_CONTROL_URL)
        return f": HTTP {response.status_code}"

    @property
    def ttl_seconds(self) -> int:
        return self._ttl
