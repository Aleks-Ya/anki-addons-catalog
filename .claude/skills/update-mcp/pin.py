"""Move the app to another anki-addons-mcp version: the pin, the lock and the environment. Run it only after the user
approved the upgrade.

Usage: uv run python .claude/skills/update-mcp/pin.py <target>   (a version X.Y.Z)
Run from the repository root. Sets `anki-addons-mcp==<target>` in pyproject.toml, runs `uv lock --upgrade-package
anki-addons-mcp` (only the MCP server and what its new version needs move) and `uv sync`, then prints one
"PASS|FAIL <check>: <detail>" line per check (the pin and uv.lock name the target) and one "moved: <package> <old> ->
<new>" line per package whose locked version changed against HEAD. Exits 0 when all checks pass, 1 otherwise.
"""
import subprocess
import sys
import tomllib
from pathlib import Path

from mcp_repo import Check, locked_mcp_version, mcp_dependency, pinned_version, print_checks, set_pin


def locked_versions(lock: str) -> dict[str, str]:
    return {p["name"]: p.get("version", "") for p in tomllib.loads(lock)["package"]}


def moved(before: dict[str, str], after: dict[str, str]) -> list[str]:
    names = sorted(before.keys() | after.keys())
    return [f"moved: {n} {before.get(n, 'none')} -> {after.get(n, 'none')}" for n in names
            if before.get(n) != after.get(n)]


def version_check(what: str, actual: str | None, target: str) -> Check:
    return actual == target, f"{what} has {actual}, expected {target}"


def main(target: str) -> int:
    pyproject = Path("pyproject.toml")
    pyproject.write_text(set_pin(pyproject.read_text(), target))
    for command in (["uv", "lock", "--upgrade-package", "anki-addons-mcp"], ["uv", "sync"]):
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"FAIL {' '.join(command)}: {(result.stderr or result.stdout).strip()}")
            return 1
    lock = Path("uv.lock").read_text()
    head_lock = subprocess.run(["git", "show", "HEAD:uv.lock"], check=True, capture_output=True, text=True).stdout
    ok = print_checks([("pin", version_check("pyproject.toml", pinned_version(mcp_dependency(pyproject.read_text())),
                                             target)),
                       ("lock", version_check("uv.lock", locked_mcp_version(lock), target))])
    for line in moved(locked_versions(head_lock), locked_versions(lock)):
        print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
