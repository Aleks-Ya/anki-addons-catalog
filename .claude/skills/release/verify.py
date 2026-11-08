"""Check the state /release needs before it starts and after each of its two commits.

Usage: python3 verify.py pre | release <version> | dev <version>
pre: on main, a clean tree (bump-my-version refuses a dirty one), main pushed (it fetches origin first; the released
code must have been through /push), and gh logged in (for the GitHub Release).
release <version>: HEAD is the release commit `Bump version: ... → <version>` tagged v<version>, touching only the
version files, with a clean tree.
dev <version>: HEAD is the untagged development commit `Bump version: <version> → <next minor>.dev0` on top of that
release commit, both touching only the version files, with a clean tree.
Run from the repository root. Prints one "PASS|FAIL <check>: <detail>" line per check; exits 0 when all pass.
"""
import re
import subprocess
import sys

VERSION_FILE = "src/anki_addons_catalog/__init__.py"
VERSION_FILES = {VERSION_FILE, ".bumpversion.toml"}
Check = tuple[str, bool, str]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def next_dev(version: str) -> str:
    major, minor, _ = map(int, version.split("."))
    return f"{major}.{minor + 1}.0.dev0"


def file_version() -> str:
    with open(VERSION_FILE) as f:
        match = re.search(r'__version__ = "([^"]+)"', f.read())
    return match.group(1) if match else "?"


def clean() -> Check:
    status = git("status", "--porcelain")
    return "clean tree", not status, status.replace("\n", ", ") or "nothing to commit"


def commit(rev: str, subject: str, tag: str | None) -> list[Check]:
    """The commit at `rev` has `subject`, touches only the version files and has exactly `tag` (or no tag)."""
    actual = git("log", "-1", "--format=%s", rev)
    files = set(git("show", "--name-only", "--format=", rev).splitlines())
    tags = git("tag", "--points-at", rev).splitlines()
    return [
        (f"{rev} subject", re.fullmatch(subject, actual) is not None, actual),
        (f"{rev} files", files == VERSION_FILES, ", ".join(sorted(files))),
        (f"{rev} tag", tags == ([tag] if tag else []), ", ".join(tags) or "no tag"),
    ]


def pre() -> list[Check]:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    git("fetch", "-q", "origin")
    ahead = git("log", "--oneline", "origin/main..main").replace("\n", ", ")
    behind = git("log", "--oneline", "main..origin/main").replace("\n", ", ")
    gh = subprocess.run(["gh", "auth", "status"], check=False, capture_output=True, text=True)
    return [
        ("branch", branch == "main", branch),
        clean(),
        ("main pushed", not ahead and not behind,
         "main equals origin/main" if not ahead and not behind
         else f"only on main: {ahead or 'none'}; only on origin/main: {behind or 'none'}; run /push first"),
        ("gh auth", gh.returncode == 0, "logged in" if gh.returncode == 0 else (gh.stderr or gh.stdout).strip()),
    ]


def release(version: str) -> list[Check]:
    current = file_version()
    return [*commit("HEAD", rf"Bump version: \S+ → {re.escape(version)}", f"v{version}"),
            ("__version__", current == version, current), clean()]


def dev(version: str) -> list[Check]:
    expected, current = next_dev(version), file_version()
    return [*commit("HEAD~1", rf"Bump version: \S+ → {re.escape(version)}", f"v{version}"),
            *commit("HEAD", re.escape(f"Bump version: {version} → {expected}"), None),
            ("__version__", current == expected, f"{current}, expected {expected}"), clean()]


if __name__ == "__main__":
    mode = sys.argv[1]
    checks = pre() if mode == "pre" else release(sys.argv[2]) if mode == "release" else dev(sys.argv[2])
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    sys.exit(0 if all(ok for _, ok, _ in checks) else 1)
