"""The anki-addons-mcp releases and the app's pin on them: the helpers the /update-mcp scripts share.

The MCP repo is read through GitHub (`gh api`) only, so the local ../anki-addons-mcp stays untouched (no fetch).
Run the scripts with `uv run python` from the repository root.
"""
import ast
import json
import re
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy"))
from smoke import locked_version  # shared with /deploy

REPO = "Aleks-Ya/anki-addons-mcp"
PACKAGE = "anki-addons-mcp"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
_PIN = re.compile(r"anki-addons-mcp\s*==\s*(\d+\.\d+\.\d+)")
_PIN_IN_FILE = re.compile(r'"anki-addons-mcp[^"]*"')
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

Version = tuple[int, int, int]
Check = tuple[bool, str]


def parse_version(text: str) -> Version | None:
    """A plain release X.Y.Z (or tag vX.Y.Z) as numbers; None for anything else (e.g. backup or dev tags)."""
    match = _VERSION.fullmatch(text)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def mcp_dependency(pyproject: str) -> str | None:
    """The anki-addons-mcp requirement in pyproject.toml, as written."""
    deps = tomllib.loads(pyproject)["project"]["dependencies"]
    return next((d for d in deps if re.match(r"anki-addons-mcp\b", d)), None)


def pinned_version(dependency: str | None) -> str | None:
    """The exact version of an `anki-addons-mcp==X.Y.Z` requirement; None for a range or no requirement."""
    match = _PIN.fullmatch(dependency or "")
    return match[1] if match else None


def set_pin(pyproject: str, version: str) -> str:
    """pyproject.toml with the anki-addons-mcp requirement replaced by `==version`."""
    if len(_PIN_IN_FILE.findall(pyproject)) != 1:
        raise SystemExit("pyproject.toml must name anki-addons-mcp exactly once")
    return _PIN_IN_FILE.sub(f'"{PACKAGE}=={version}"', pyproject)


def locked_mcp_version(lock: str) -> str | None:
    """The anki-addons-mcp version a uv.lock locks."""
    return locked_version(lock, PACKAGE)


def read(path: str) -> str:
    return Path(path).read_text()


def gh_api(path: str, *args: str) -> str:
    result = subprocess.run(["gh", "api", *args, path], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"gh api {path} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def release_tags() -> list[str]:
    """The MCP release tags (vX.Y.Z), newest first."""
    names = gh_api(f"repos/{REPO}/tags?per_page=100", "--paginate", "--jq", ".[].name").split()
    return sorted((n for n in names if parse_version(n)), key=lambda n: parse_version(n) or (0, 0, 0), reverse=True)


def compare(base: str, head: str) -> dict[str, Any]:
    """GitHub's comparison of two refs: `total_commits`, `commits` (oldest first) and `files` with their patches."""
    return json.loads(gh_api(f"repos/{REPO}/compare/{base}...{head}"))  # type: ignore[no-any-return]


def file_at(path: str, ref: str) -> str | None:
    """A file of the MCP repo at a ref; None when it doesn't exist there."""
    result = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw",
                             f"repos/{REPO}/contents/{path}?ref={ref}"], check=False, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def pypi_versions() -> set[str]:
    """The versions on PyPI that can be installed (not yanked)."""
    with urllib.request.urlopen(PYPI_URL, timeout=30) as response:
        releases = json.load(response)["releases"]
    return {v for v, files in releases.items() if files and not all(f.get("yanked") for f in files)}


def is_routine(subject: str) -> bool:
    """Version bumps and lock upgrades: commits that say nothing about what changed for the app."""
    return subject.startswith("Bump version:") or subject == "Upgrade dependencies"


def subjects(comparison: dict[str, Any]) -> list[str]:
    """The subjects of the compared commits, oldest first, without the routine ones."""
    lines = [c["commit"]["message"].splitlines()[0] for c in comparison["commits"]]
    return [s for s in lines if not is_routine(s)]


def hf_revision(config: str | None) -> str | None:
    """The dataset tag the MCP server pins: the `hf_revision` default in its config.py."""
    match = re.search(r'hf_revision:\s*str\s*=\s*"([^"]+)"', config or "")
    return match[1] if match else None


def mcp_imports(roots: tuple[str, ...] = ("src", "tests")) -> dict[str, set[str]]:
    """What the app imports from anki-addons-mcp: module -> imported names, from every Python file under `roots`."""
    imports: dict[str, set[str]] = {}
    for path in sorted(p for root in roots for p in Path(root).rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "anki_addons_mcp":
                imports.setdefault(node.module, set()).update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "anki_addons_mcp":
                        imports.setdefault(alias.name, set())
    return imports


def module_files(module: str) -> list[str]:
    """The files of the MCP repo that can hold a module: the module file, or the package's __init__.py."""
    base = "src/" + module.replace(".", "/")
    return [f"{base}.py", f"{base}/__init__.py"]


def print_checks(checks: list[tuple[str, Check]]) -> bool:
    for name, (ok, detail) in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    return all(ok for _, (ok, _) in checks)
