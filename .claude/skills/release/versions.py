"""Print the current version and the major, minor and patch versions /release offers.

A .dev0 version is not released yet, so the candidates count from the last release tag (or from the dev version
without its suffix when there is no tag). A release version counts from itself: 1.2.2 -> 2.0.0, 1.3.0, 1.2.3.
Run from the repository root.
"""
import re
import subprocess
import tomllib


def current_version() -> str:
    with open(".bumpversion.toml", "rb") as f:
        return str(tomllib.load(f)["tool"]["bumpversion"]["current_version"])


def last_release_tag() -> str:
    result = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"],
                            check=False, capture_output=True, text=True)  # no tag yet is fine
    return result.stdout.strip()


def candidates(current: str, tag: str) -> dict[str, str]:
    base = current if ".dev" not in current else (tag.removeprefix("v") or current.split(".dev")[0])
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", base)
    if not match:
        raise SystemExit(f"Cannot parse version {base!r} (current {current!r}, tag {tag!r})")
    major, minor, patch = map(int, match.groups())
    return {"major": f"{major + 1}.0.0", "minor": f"{major}.{minor + 1}.0", "patch": f"{major}.{minor}.{patch + 1}"}


if __name__ == "__main__":
    current, tag = current_version(), last_release_tag()
    print(f"current: {current}")
    print(f"last release tag: {tag or 'none'}")
    for part, version in candidates(current, tag).items():
        print(f"{part}: {version}")
