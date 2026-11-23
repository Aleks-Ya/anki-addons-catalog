from typing import Any

import httpx
import pytest

from anki_addons_catalog.interface.web import security
from anki_addons_catalog.interface.web.security import IPV6, PROBE_TEST_SECRET, HumanCheck

pytestmark = pytest.mark.anyio

V4, V6 = "192.0.2.1", "2001:db8::1"  # documentation addresses


def probe_lines(caplog: pytest.LogCaptureFixture) -> dict[str, tuple[str, str]]:
    """The `Turnstile probe:` lines by check name, as (level, text)."""
    lines = {}
    for record in caplog.records:
        message = record.getMessage()
        if message.startswith("Turnstile probe: "):
            text = message.removeprefix("Turnstile probe: ")
            name = text.split(" ok in ")[0].split(" failed")[0].split(": ")[0]
            lines[name] = (record.levelname, text)
    return lines


def prober(monkeypatch: pytest.MonkeyPatch, fail_v6: bool = True,
           fail_dns: bool = False) -> tuple[HumanCheck, list[dict[str, str]]]:
    """A HumanCheck whose network is fake: TCP and HTTPS over IPv6 fail when `fail_v6`, the rest works."""
    sent: list[dict[str, str]] = []

    async def resolve(host: str) -> list[str]:
        if fail_dns:
            raise OSError("Name or service not known")
        return [V6, V4]

    async def connect(address: str) -> None:
        if fail_v6 and ":" in address:
            raise TimeoutError

    def handler(local_address: str | None) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            if fail_v6 and local_address == IPV6:
                raise httpx.ConnectTimeout("")
            if request.method == "POST":
                sent.append(dict(httpx.QueryParams(request.content.decode())))
                return httpx.Response(200, json={"success": True})
            return httpx.Response(200)
        return httpx.MockTransport(handle)

    monkeypatch.setattr(security, "resolve", resolve)
    monkeypatch.setattr(security, "connect", connect)
    human = HumanCheck("site", "the-real-secret", "s", 3600, transport=handler(None), family_transport=handler)
    return human, sent


async def test_probe_logs_each_check(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    human, sent = prober(monkeypatch)
    await human.probe()
    lines = probe_lines(caplog)
    assert lines["DNS challenges.cloudflare.com"] == ("INFO", f"DNS challenges.cloudflare.com: {V6}, {V4}")
    assert lines[f"TCP {V4}:443"][0] == "INFO" and lines[f"TCP {V6}:443"][0] == "WARNING"
    assert "TimeoutError" in lines[f"TCP {V6}:443"][1]
    assert lines["HTTPS siteverify, default"][0] == "INFO"
    assert "HTTP 200, success True" in lines["HTTPS siteverify, IPv4"][1]
    assert lines["HTTPS siteverify, IPv6"][0] == "WARNING" and "ConnectTimeout" in lines["HTTPS siteverify, IPv6"][1]
    assert lines["HTTPS https://www.cloudflare.com/"][0] == "INFO"
    assert {form["secret"] for form in sent} == {PROBE_TEST_SECRET}
    assert "the-real-secret" not in caplog.text


async def test_probe_never_raises(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    human, _ = prober(monkeypatch, fail_dns=True)
    await human.probe()
    lines = probe_lines(caplog)
    assert lines["DNS challenges.cloudflare.com"][0] == "WARNING" and not any(n.startswith("TCP") for n in lines)
    assert "HTTPS siteverify, IPv4" in lines


async def test_a_network_error_starts_one_probe_per_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    probes: list[Any] = []

    async def probe(self: HumanCheck) -> None:
        probes.append(self)
    monkeypatch.setattr(HumanCheck, "probe", probe)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("")
    human = HumanCheck("site", "secret", "s", 3600, transport=httpx.MockTransport(handler))

    assert not await human.verify("token", "1.2.3.4")
    assert human._probe_task is not None
    await human._probe_task
    assert not await human.verify("token", "1.2.3.4")  # within PROBE_INTERVAL_SECONDS
    assert len(probes) == 1


async def test_no_probe_when_turnstile_is_off() -> None:
    assert HumanCheck("site", None, "s", 3600).start_probe() is None
