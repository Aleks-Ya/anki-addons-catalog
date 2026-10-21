from typing import Any

import pytest
from anki_addons_mcp.config import Settings as McpSettings
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer

from anki_addons_catalog import bootstrap
from anki_addons_catalog.adapters.mcp.catalog import McpCatalog
from anki_addons_catalog.bootstrap import create_app, mcp_auth_headers
from anki_addons_catalog.config import Settings
from tests.conftest import FakeLlm


def test_hf_space_gets_the_proxy_header() -> None:
    assert mcp_auth_headers("https://ya-alex-anki-addons-mcp.hf.space/mcp", "hf_x") == {
        "X-HF-Authorization": "Bearer hf_x"}


def test_other_hosts_get_authorization() -> None:
    assert mcp_auth_headers("http://localhost:8000/mcp", "hf_x") == {"Authorization": "Bearer hf_x"}
    assert mcp_auth_headers("https://evil-hf.space.example/mcp", "hf_x") == {"Authorization": "Bearer hf_x"}


def test_no_token_no_header() -> None:
    assert mcp_auth_headers("https://ya-alex-anki-addons-mcp.hf.space/mcp", None) == {}


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, HF_TOKEN="hf_x", usage_db=":memory:",  # type: ignore[call-arg]
                    mcp_keepalive_seconds=0, **overrides)


def test_without_mcp_url_the_mcp_server_runs_in_process(monkeypatch: pytest.MonkeyPatch, server: MCPServer) -> None:
    created: list[McpSettings] = []

    def create_mcp_app(mcp_settings: McpSettings) -> tuple[MCPServer, Any]:
        created.append(mcp_settings)
        return server, None

    monkeypatch.setattr(bootstrap, "create_mcp_app", create_mcp_app)
    with TestClient(create_app(settings(), llm=FakeLlm([]))) as client:
        assert client.get("/").status_code == 200
    assert [s.hf_token for s in created] == ["hf_x"]


def test_with_mcp_url_the_remote_server_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    remote: list[tuple[Any, dict[str, str]]] = []

    def create_mcp_app(mcp_settings: McpSettings) -> tuple[MCPServer, Any]:
        raise AssertionError("the in-process MCP server must not start")

    class RecordingCatalog(McpCatalog):
        def __init__(self, server: Any, timeout_seconds: float = 120.0, headers: dict[str, str] | None = None) -> None:
            remote.append((server, headers or {}))
            super().__init__(server, timeout_seconds, headers)

    monkeypatch.setattr(bootstrap, "create_mcp_app", create_mcp_app)
    monkeypatch.setattr(bootstrap, "McpCatalog", RecordingCatalog)
    create_app(settings(mcp_url="https://ya-alex-anki-addons-mcp.hf.space/mcp"), llm=FakeLlm([]))
    assert remote == [("https://ya-alex-anki-addons-mcp.hf.space/mcp", {"X-HF-Authorization": "Bearer hf_x"})]
