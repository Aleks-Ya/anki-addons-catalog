from anki_addons_catalog.bootstrap import mcp_auth_headers


def test_hf_space_gets_the_proxy_header() -> None:
    assert mcp_auth_headers("https://ya-alex-anki-addons-mcp.hf.space/mcp", "hf_x") == {
        "X-HF-Authorization": "Bearer hf_x"}


def test_other_hosts_get_authorization() -> None:
    assert mcp_auth_headers("http://localhost:8000/mcp", "hf_x") == {"Authorization": "Bearer hf_x"}
    assert mcp_auth_headers("https://evil-hf.space.example/mcp", "hf_x") == {"Authorization": "Bearer hf_x"}


def test_no_token_no_header() -> None:
    assert mcp_auth_headers("https://ya-alex-anki-addons-mcp.hf.space/mcp", None) == {}
