"""List the anki-addons-mcp releases newer than the pinned version and recommend one for /update-mcp.

Usage: uv run python .claude/skills/update-mcp/releases.py [--target X.Y.Z]
Run from the repository root. Prints the pinned version, then one block per newer release, oldest first: its date,
whether it is on PyPI (only those can be installed) and its commits without the version bumps; then
"recommended: <the newest release on PyPI>", and the commits on the MCP's main after the newest tag (not released,
so not adoptable). Exits 0 when a newer release exists and 2 when the pin is the newest release.
With --target it checks the user's choice instead (a release tag newer than the pin and on PyPI): it prints "ok" and
exits 0, or prints why not and exits 1.
"""
import argparse
import sys

from mcp_repo import (
    Version,
    compare,
    mcp_dependency,
    parse_version,
    pinned_version,
    pypi_versions,
    read,
    release_tags,
    subjects,
)


def newer(tags: list[str], pinned: str) -> list[str]:
    """The release tags after the pinned version, oldest first."""
    return sorted((t for t in tags if _key(t) > _key(pinned)), key=_key)


def _key(tag: str) -> Version:
    return parse_version(tag) or (0, 0, 0)


def recommended(tags: list[str], on_pypi: set[str]) -> str | None:
    """The newest of the newer releases that PyPI has."""
    return next((t.removeprefix("v") for t in reversed(tags) if t.removeprefix("v") in on_pypi), None)


def invalid(target: str, pinned: str, tags: list[str], on_pypi: set[str]) -> str | None:
    """Why `target` can't be the upgrade, or None when it can."""
    version = parse_version(target)
    if version is None:
        return f"{target!r} is not a plain X.Y.Z version"
    if version <= (parse_version(pinned) or (0, 0, 0)):
        return f"{target} is not newer than the pinned {pinned}"
    if f"v{target}" not in tags:
        return f"the MCP repo has no tag v{target}"
    if target not in on_pypi:
        return f"{target} is not on PyPI (yet): the release workflow publishes it"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target")
    args = parser.parse_args()
    pinned = pinned_version(mcp_dependency(read("pyproject.toml")))
    if pinned is None:
        print("pyproject.toml does not pin an exact anki-addons-mcp version: run ready.py")
        return 1
    tags, on_pypi = release_tags(), pypi_versions()
    if args.target:
        problem = invalid(args.target, pinned, tags, on_pypi)
        print(problem or "ok")
        return 1 if problem else 0
    print(f"pinned: {pinned}")
    candidates = newer(tags, pinned)
    previous = f"v{pinned}"
    for tag in candidates:
        comparison = compare(previous, tag)
        date = comparison["commits"][-1]["commit"]["committer"]["date"][:10] if comparison["commits"] else "?"
        where = "on PyPI" if tag.removeprefix("v") in on_pypi else "NOT on PyPI"
        print(f"release {tag.removeprefix('v')}: {date}, {where}, {comparison['total_commits']} commits since"
              f" {previous}")
        for subject in subjects(comparison):
            print(f"  - {subject}")
        previous = tag
    newest = tags[0] if tags else f"v{pinned}"
    unreleased = subjects(compare(newest, "main"))  # a lone "Bump version" to the next .dev0 is no news
    if unreleased:
        print(f"unreleased: {len(unreleased)} commit(s) on main after {newest}, not adoptable until released")
        for subject in unreleased:
            print(f"  - {subject}")
    best = recommended(candidates, on_pypi)
    if best is None:
        print(f"up to date: {pinned} is the newest release on PyPI")
        return 2
    print(f"recommended: {best}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
