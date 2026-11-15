"""Check the commit /update-mcp made: the upgrade to anki-addons-mcp <target> is committed, whole.

Usage: uv run python .claude/skills/update-mcp/verify_upgrade.py <target>   (a version X.Y.Z)
Run from the repository root. Prints one "PASS|FAIL <check>: <detail>" line per check: HEAD's subject starts with
"Upgrade to anki-addons-mcp <target>", HEAD's pyproject.toml pins and its uv.lock locks <target>, and nothing is left
uncommitted. Exits 0 when all pass, 1 otherwise.
"""
import subprocess
import sys

from mcp_repo import Check, locked_mcp_version, mcp_dependency, pinned_version, print_checks


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def subject(actual: str, target: str) -> Check:
    return actual.startswith(f"Upgrade to anki-addons-mcp {target}"), actual


def version(what: str, actual: str | None, target: str) -> Check:
    return actual == target, f"{what} at HEAD has {actual}, expected {target}"


def committed(status: str) -> Check:
    return not status, ", ".join(line.strip() for line in status.splitlines()) or "clean tree"


def main(target: str) -> int:
    checks = [
        ("subject", subject(git("log", "-1", "--format=%s"), target)),
        ("pin", version("pyproject.toml", pinned_version(mcp_dependency(git("show", "HEAD:pyproject.toml"))), target)),
        ("lock", version("uv.lock", locked_mcp_version(git("show", "HEAD:uv.lock")), target)),
        ("committed", committed(git("status", "--porcelain"))),
    ]
    return 0 if print_checks(checks) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
