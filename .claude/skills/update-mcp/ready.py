"""Check what /update-mcp needs before it looks for a new MCP version.

Usage: uv run python .claude/skills/update-mcp/ready.py
Run from the repository root. Prints one "PASS|FAIL <check>: <detail>" line per check: the branch is main, nothing is
uncommitted (the upgrade becomes one reviewable commit), pyproject.toml pins an exact anki-addons-mcp version, and
uv.lock locks the same version. Exits 0 when all pass, 1 otherwise.
"""
import subprocess
import sys

from mcp_repo import Check, locked_mcp_version, mcp_dependency, pinned_version, print_checks, read


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def branch(name: str) -> Check:
    return name == "main", name


def committed(status: str) -> Check:
    """From `git status --porcelain`: whether the tree is clean, else the uncommitted files."""
    return not status, ", ".join(line.strip() for line in status.splitlines()) or "clean tree"


def pin(dependency: str | None) -> Check:
    if pinned_version(dependency):
        return True, str(dependency)
    return False, f"{dependency or 'no anki-addons-mcp requirement'}: pin an exact version (anki-addons-mcp==X.Y.Z)"


def lock(pinned: str | None, locked: str | None) -> Check:
    return pinned is not None and pinned == locked, f"uv.lock has {locked}, pyproject.toml pins {pinned}"


def main() -> int:
    dependency = mcp_dependency(read("pyproject.toml"))
    checks = [
        ("branch", branch(git("rev-parse", "--abbrev-ref", "HEAD"))),
        ("committed", committed(git("status", "--porcelain"))),
        ("pin", pin(dependency)),
        ("lock", lock(pinned_version(dependency), locked_mcp_version(read("uv.lock")))),
    ]
    return 0 if print_checks(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
