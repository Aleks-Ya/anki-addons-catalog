import json
import sys

import local_check
import pytest


def test_startup() -> None:
    assert local_check.startup("INFO MCP server: in-process\nINFO Dataset loaded") == "ready"
    assert local_check.startup("ERROR Warm-up failed; data will be loaded on first request") == "failed"
    assert local_check.startup("INFO MCP server: in-process") is None
    assert local_check.in_process("x INFO MCP server: in-process\n") == (True, "MCP server: in-process")
    assert not local_check.in_process("x INFO MCP server: http://localhost:8000/mcp, token\n")[0]


def test_costs() -> None:
    jsonl = "\n".join(json.dumps(q) for q in [{"query": "kanji", "outcome": "answered", "cost_usd": 0.031},
                                              {"query": "x", "outcome": "failed", "cost_usd": None}])
    lines, total = local_check.costs(jsonl)
    assert lines == ["cost: $0.0310 answered 'kanji'", "cost: $0.0000 failed 'x'"]
    assert total == pytest.approx(0.031)


def test_local_check_limits_questions(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["local_check.py", "0.12.0", *[a for i in range(4) for a in ("--ask", f"q{i}")]])
    assert local_check.main() == 1
    assert "at most 3" in capsys.readouterr().out


@pytest.mark.parametrize(("target", "about"), [(None, False), ("0.12.1", True)])
def test_about_is_checked_only_with_a_target(monkeypatch: pytest.MonkeyPatch, target: str | None, about: bool) -> None:
    monkeypatch.setattr(local_check, "fetch", lambda url, headers, timeout=60: (200, ""))
    names = [name for name, _ in local_check.checks("http://x", target, ["/p"], [], {}, "")]
    assert any(name.startswith("about") for name in names) == about
    assert "page /p" in names
