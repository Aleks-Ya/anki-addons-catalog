import json
import sys
from pathlib import Path

import changes
import impact
import local_check
import mcp_repo
import pin
import pytest
import ready
import releases
import verify_upgrade

PYPROJECT = """[project]
name = "app"
dependencies = [
    "fastapi",
    "anki-addons-mcp==0.11.0",
]
"""

TOOLS_SOURCE = '''
def register_tools(mcp, services):
    @mcp.tool(annotations=READ_ONLY, description="Search")
    def search_addons(query: str, limit: int = 10, *, primary_language: str | None = None):
        pass

    @mcp.tool(name="get_addon_record")
    def get_addon(addon_id: int):
        pass

    def helper(x):
        pass
'''

MODELS_BASE = '''
LICENSE = "The addon's license"

class GithubInfo(BaseModel):
    languages: list[str] = Field(default_factory=list)
    license: str | None = None
    stars: int = 0

class AddonCard(BaseModel):
    license: str | None = Field(default=None, description=LICENSE)
'''

MODELS_TARGET = '''
LICENSE = "The resolved license"

class GithubInfo(BaseModel):
    license: str | None = None
    stars: float = 0

class AddonCard(BaseModel):
    license: str | None = Field(default=None, description=LICENSE)
    primary_language: str | None = None
'''


def commit(message: str, date: str = "2026-11-15T06:00:00Z") -> dict[str, object]:
    return {"commit": {"message": message, "committer": {"date": date}}}


def test_parse_version() -> None:
    assert mcp_repo.parse_version("v0.12.0") == (0, 12, 0)
    assert mcp_repo.parse_version("0.10.2") == (0, 10, 2)
    assert mcp_repo.parse_version("backup-2026") is None
    assert mcp_repo.parse_version("0.13.0.dev0") is None


def test_pin() -> None:
    dependency = mcp_repo.mcp_dependency(PYPROJECT)
    assert dependency == "anki-addons-mcp==0.11.0"
    assert mcp_repo.pinned_version(dependency) == "0.11.0"
    assert mcp_repo.pinned_version("anki-addons-mcp>=0.11.0") is None
    assert mcp_repo.pinned_version(None) is None
    assert ready.pin(dependency) == (True, "anki-addons-mcp==0.11.0")
    assert not ready.pin("anki-addons-mcp>=0.11.0")[0]


def test_set_pin() -> None:
    updated = mcp_repo.set_pin(PYPROJECT, "0.12.0")
    assert '"anki-addons-mcp==0.12.0"' in updated and '"fastapi"' in updated
    assert mcp_repo.set_pin(PYPROJECT.replace("==0.11.0", ">=0.11.0"), "0.12.0") == updated
    with pytest.raises(SystemExit):
        mcp_repo.set_pin(PYPROJECT.replace('"fastapi"', '"anki-addons-mcp[x]"'), "0.12.0")


def test_lock_matches_pin() -> None:
    assert ready.lock("0.11.0", "0.11.0")[0]
    assert ready.lock("0.11.0", "0.10.2") == (False, "uv.lock has 0.10.2, pyproject.toml pins 0.11.0")
    assert not ready.lock(None, None)[0]


def test_subjects_skip_routine_commits() -> None:
    comparison = {"commits": [commit("Bump version: 0.11.0 → 0.12.0.dev0"), commit("Add a filter\n\nWhy."),
                              commit("Upgrade dependencies")]}
    assert mcp_repo.subjects(comparison) == ["Add a filter"]
    assert changes.commit_messages(comparison) == ["Add a filter\n\nWhy."]


def test_hf_revision() -> None:
    assert mcp_repo.hf_revision('class Settings:\n    hf_revision: str = "v2.0-2026-11-01"\n') == "v2.0-2026-11-01"
    assert mcp_repo.hf_revision(None) is None


def test_mcp_imports(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("from anki_addons_mcp.config import Settings as S\nfrom anki_addons_mcp import (\n"
                                   "    __version__,\n)\nimport anki_addons_mcp.bootstrap\nfrom os import path\n")
    assert mcp_repo.mcp_imports((str(tmp_path),)) == {
        "anki_addons_mcp.config": {"Settings"}, "anki_addons_mcp": {"__version__"}, "anki_addons_mcp.bootstrap": set()}
    assert mcp_repo.module_files("anki_addons_mcp.domain.models") == [
        "src/anki_addons_mcp/domain/models.py", "src/anki_addons_mcp/domain/models/__init__.py"]


def test_releases() -> None:
    tags = ["v0.12.0", "v0.11.0", "v0.10.2", "v0.9.0"]
    assert releases.newer(tags, "0.10.2") == ["v0.11.0", "v0.12.0"]
    assert releases.recommended(["v0.11.0", "v0.12.0"], {"0.11.0", "0.12.0"}) == "0.12.0"
    assert releases.recommended(["v0.11.0", "v0.12.0"], {"0.11.0"}) == "0.11.0"  # 0.12.0 not published yet
    assert releases.recommended([], {"0.11.0"}) is None


@pytest.mark.parametrize(("target", "problem"), [
    ("0.12.0", None),
    ("0.11.0", "0.11.0 is not newer than the pinned 0.11.0"),
    ("0.9.0", "0.9.0 is not newer than the pinned 0.11.0"),
    ("0.13.0", "the MCP repo has no tag v0.13.0"),
    ("0.12.1", "0.12.1 is not on PyPI (yet): the release workflow publishes it"),
    ("1.0", "'1.0' is not a plain X.Y.Z version"),
])
def test_invalid_target(target: str, problem: str | None) -> None:
    assert releases.invalid(target, "0.11.0", ["v0.12.1", "v0.12.0", "v0.11.0"], {"0.11.0", "0.12.0"}) == problem


def test_sections() -> None:
    files = [{"filename": n, "status": "modified", "additions": 1, "deletions": 0, "patch": "@@"} for n in
             ["src/anki_addons_mcp/domain/models.py", "src/anki_addons_mcp/bootstrap.py", "README.md", "uv.lock"]]
    result = changes.sections(files, ["src/anki_addons_mcp/bootstrap.py", "src/anki_addons_mcp/domain/models.py"])
    assert [(title, [f["filename"] for f in chosen]) for title, chosen in result] == [
        ("MCP surface the AI uses", ["src/anki_addons_mcp/domain/models.py"]),
        ("Other MCP modules the app imports", ["src/anki_addons_mcp/bootstrap.py"]),
        ("User docs", ["README.md"]),
        ("MCP test fixture (real data shapes)", []),
        ("Other changed files (no patch shown)", ["uv.lock"]),
    ]


def test_tools() -> None:
    assert impact.tools(TOOLS_SOURCE) == {"search_addons": {"query", "limit", "primary_language"},
                                          "get_addon_record": {"addon_id"}}


def test_top_level_names() -> None:
    source = "from x import y as z\nimport a.b\nA = 1\nB: int = 2\nclass C: pass\ndef d(): pass\n"
    assert impact.top_level_names(source) == {"z", "a", "A", "B", "C", "d"}


def test_direct_calls_and_filter_arguments() -> None:
    source = ('async def f(self, args):\n    await self.call("get_addon", addon_id=1, include=["links"])\n'
              '    await self.call("search_addons", query="q", **args)\n'
              '    await catalog.call_tool("get_addon", {"addon_id": 2})\n    self.call(name)\n')
    assert impact.direct_calls([source]) == {"get_addon": {"addon_id", "include"}, "search_addons": {"query"}}
    models = ('class SearchFilters:\n    def tool_args(self, today):\n        args = {"tags": self.tags}\n'
              '        args["compatible_with_anki"] = self.anki\n        return args\n')
    assert impact.filter_arguments(models) == {"tags", "compatible_with_anki"}


def test_prompt_tools() -> None:
    assert impact.prompt_tools("Call search_addons, then get_addon.", {"search_addons", "get_addon", "x"}) == {
        "search_addons", "get_addon"}


def test_argument_checks() -> None:
    target = {"search_addons": {"query", "tags"}}
    assert impact.argument_checks({"search_addons": {"query", "language"}, "gone": set()}, target) == [
        ("call gone", (False, "the tool is gone")),
        ("call search_addons", (False, "unknown arguments: language")),
    ]
    assert impact.tool_checks("ai_tools", {"search_addons", "top_addons"}, target) == [
        ("ai_tools", (False, "missing at the target: top_addons"))]


def test_import_checks() -> None:
    sources: dict[str, str | None] = {"src/anki_addons_mcp/config.py": "class Settings: pass\n",
                                      "src/anki_addons_mcp/config/__init__.py": None}
    assert impact.import_checks({"anki_addons_mcp.config": {"Settings", "Other"}, "anki_addons_mcp.gone": {"x"}},
                                sources) == [
        ("import anki_addons_mcp.config", (False, "missing names: Other")),
        ("import anki_addons_mcp.gone", (False, "the module is gone")),
    ]


def test_field_findings() -> None:
    base, target = impact.model_fields(MODELS_BASE), impact.model_fields(MODELS_TARGET)
    assert base["AddonCard.license"] == ("str | None", "The addon's license")
    files = {"addon.html": "{{ gh.languages }}\n{{ gh.license }}", "models.py": "stars = 1"}
    checks, lines = impact.field_findings(base, target, files)
    assert checks == [
        ("field GithubInfo.languages", (False, "removed; the app names 'languages' in addon.html:1")),
        ("field GithubInfo.stars", (False, "type int -> float; the app names 'stars' in models.py:1")),
    ]
    assert lines == ["NEW field AddonCard.primary_language: str | None",
                     ("INFO field AddonCard.license description changed, the app names 'license' in addon.html:2: "
                      "'The resolved license'")]


def test_news() -> None:
    base = {"search_addons": {"query"}, "old_tool": set(), "used_tool": set()}
    target = {"search_addons": {"query", "primary_language"}, "new_tool": set()}
    assert impact.news(base, target, {"used_tool"}) == [
        "NEW tool new_tool: not in ai_tools, so the AI can't call it",
        "NEW parameters of search_addons: primary_language",
        "INFO tool old_tool removed (the app doesn't use it)",
    ]


def test_moved() -> None:
    lock = '[[package]]\nname = "anki-addons-mcp"\nversion = "0.12.0"\n\n[[package]]\nname = "app"\nsource = {}\n'
    after = pin.locked_versions(lock)
    assert after == {"anki-addons-mcp": "0.12.0", "app": ""}
    assert pin.moved({"anki-addons-mcp": "0.11.0", "app": "", "gone": "1.0"}, {**after, "duckdb": "2.1"}) == [
        "moved: anki-addons-mcp 0.11.0 -> 0.12.0", "moved: duckdb none -> 2.1", "moved: gone 1.0 -> none"]


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


def test_verify_upgrade_subject() -> None:
    assert verify_upgrade.subject("Upgrade to anki-addons-mcp 0.12.0 and show languages", "0.12.0")[0]
    assert not verify_upgrade.subject("Upgrade to anki-addons-mcp 0.11.0", "0.12.0")[0]
