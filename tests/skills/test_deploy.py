import json

import check_build
import plan_push
import pytest
import smoke
from space import TARGETS, get_target

TARGET = "a" * 40
PREVIOUS = "b" * 40


def build_log(sha: str, *steps: str) -> list[str]:
    return ["===== Build Queued at 2026-11-08 09:00:00 / Commit SHA: old1234 =====", "--> COPY src /app/src",
            "DONE 0.1s", f"===== Build Queued at 2026-11-08 10:00:00 / Commit SHA: {sha[:7]} =====", *steps]


def test_check_build_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_build, "changed", lambda previous, target, paths: True)
    assert check_build.check(build_log(TARGET, "--> COPY src /app/src", "DONE 0.2s"), TARGET, PREVIOUS) == []


def test_check_build_cached_copy_of_changed_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_build, "changed", lambda previous, target, paths: paths == ["src"])
    lines = build_log(TARGET, "--> COPY pyproject.toml uv.lock /app/", "CACHED", "--> COPY src /app/src", "CACHED",
                      "--> COPY --from=uv /uv /bin/uv", "CACHED")
    assert check_build.check(lines, TARGET, PREVIOUS) == [
        "'COPY src /app/src' was CACHED although src changed since bbbbbbb"]


def test_check_build_other_commit() -> None:
    assert check_build.check(build_log("c" * 40), TARGET, PREVIOUS) == ["the latest build is for ccccccc, not aaaaaaa"]
    assert check_build.check([], TARGET, PREVIOUS) == ["no build found in the log"]


def test_get_target() -> None:
    assert get_target("staging").private and not get_target("production").private
    assert {t.remote for t in TARGETS.values()} == {"space", "space-staging"}
    with pytest.raises(SystemExit):
        get_target("prod")


@pytest.mark.parametrize(("remote", "stage", "running", "fast_forward", "known", "mode"), [
    (TARGET, "RUNNING", TARGET, True, False, "none"),
    (TARGET, "BUILDING", PREVIOUS, True, False, "push"),  # pushed before, but not running yet
    (None, "NO_APP_FILE", None, False, False, "push"),  # an empty Space
    (PREVIOUS, "RUNNING", PREVIOUS, True, False, "push"),
    (PREVIOUS, "RUNNING", PREVIOUS, False, True, "rollback"),
    (PREVIOUS, "RUNNING", PREVIOUS, False, False, "foreign"),
])
def test_plan_push_decide(remote: str | None, stage: str, running: str | None, fast_forward: bool, known: bool,
                          mode: str) -> None:
    assert plan_push.decide(TARGET, remote, stage, running, fast_forward, known) == mode


def test_plan_push_command() -> None:
    staging = get_target("staging")
    assert plan_push.command("push", TARGET, PREVIOUS, staging) == f"git push space-staging {TARGET}:refs/heads/main"
    assert plan_push.command("rollback", TARGET, PREVIOUS, staging) == (
        f"git push --force-with-lease=refs/heads/main:{PREVIOUS} space-staging {TARGET}:refs/heads/main")


def test_health() -> None:
    assert smoke.health(200, '{"status": "ok", "version": "0.7.0"}', "0.7.0") == (True, "version 0.7.0")
    assert not smoke.health(200, '{"status": "ok", "version": "0.6.0"}', "0.7.0")[0]
    assert not smoke.health(503, "<html>Starting</html>", "0.7.0")[0]


def test_contains_and_status() -> None:
    assert smoke.contains(200, '<a class="card"></a><a class="card"></a>', 'class="card"', "cards") == (
        True, "HTTP 200, 2 cards")
    assert not smoke.contains(200, "", 'class="card"', "cards")[0]
    assert not smoke.contains(500, 'class="card"', 'class="card"', "cards")[0]
    assert smoke.ok_status(200, "") == (True, "HTTP 200") and not smoke.ok_status(404, "")[0]


def test_about() -> None:
    lock = '[[package]]\nname = "anki-addons-mcp"\nversion = "0.10.2"\n\n[[package]]\nname = "mcp"\nversion = "1.0"\n'
    version = smoke.locked_version(lock)
    assert version == "0.10.2"
    assert smoke.about(200, '<a href="x">Anki Addons MCP server</a> (v0.10.2)', version) == (True, "shows v0.10.2")
    assert not smoke.about(200, '<a href="x">Anki Addons MCP server</a> (v0.9.2) gives', version)[0]


def test_mcp_log() -> None:
    old = ["===== Application Startup at 2026-11-01 13:07:50 =====", "x: MCP server: https://mcp.example/mcp, 30s"]
    new = ["===== Application Startup at 2026-11-08 10:00:00 =====", "INFO bootstrap: MCP server: in-process",
           "INFO bootstrap: Dataset loaded"]
    assert smoke.mcp_log(old + new) == (True, "in-process, dataset loaded")
    assert smoke.mcp_log(new + old)[1] == (
        "remote MCP server https://mcp.example/mcp, 30s: the Space variable ANKI_CATALOG_MCP_URL is set")
    assert not smoke.mcp_log(["===== Application Startup at 2026-11-08 10:00:00 ====="])[0]


def sse(*events: tuple[str, object]) -> str:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


def test_answer() -> None:
    cards = {"count": 2, "html": '<div class="summary"></div>'}
    events = smoke.parse_sse(sse(("status", "Searching"), ("text", "Hi"), ("answer", {"html": "<p>Hi</p>"}),
                                 ("addons", cards), ("done", None)))
    assert smoke.answer(events, "TOKEN") == (True, "2 cards, 1 with a summary")
    assert smoke.answer(smoke.parse_sse(sse(("verify", None))), "TOKEN")[1].startswith("asked for Turnstile")
    assert smoke.answer(smoke.parse_sse(sse(("error", "Budget spent"))), "TOKEN") == (False, "error: Budget spent")
    assert not smoke.answer(smoke.parse_sse(sse(("answer", {}), ("addons", {"count": 0, "html": ""}),
                                                ("done", None))), "TOKEN")[0]


def test_env_value() -> None:
    env = "# comment\nANKI_CATALOG_ADMIN_TOKEN=abc\nANKI_CATALOG_STAGING_ADMIN_TOKEN='d=f'\n"
    assert smoke.env_value(env, "ANKI_CATALOG_ADMIN_TOKEN") == "abc"
    assert smoke.env_value(env, "ANKI_CATALOG_STAGING_ADMIN_TOKEN") == "d=f"
    assert smoke.env_value(env, "MISSING") is None
