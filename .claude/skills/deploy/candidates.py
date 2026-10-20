"""Print the commits /deploy offers: the development heads of main and the latest release on them.

local: the tip of the local main branch, which may not be pushed yet.
dev: the tip of origin/main (usually a .dev0 version right after /release).
release: the newest commit on main or origin/main whose __version__ is a plain X.Y.Z (the /release commit; it may be
untagged or unpushed).
space: what the `space` remote's main is now.
Each line is "<name>: <sha> <version> <pushed|unpushed>", where pushed means the commit is on origin/main, or
"<name>: none". Run from the repository root after `git fetch --multiple origin space`.
"""
import re
import subprocess

VERSION_FILE = "src/anki_addons_catalog/__init__.py"
RELEASE = re.compile(r"\d+\.\d+\.\d+")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def version_at(sha: str) -> str:
    match = re.search(r'__version__ = "([^"]+)"', git("show", f"{sha}:{VERSION_FILE}"))
    return match.group(1) if match else "?"


def latest_release(*refs: str) -> str | None:
    for sha in git("log", "--format=%H", *refs, "--", VERSION_FILE).splitlines():
        if RELEASE.fullmatch(version_at(sha)):
            return sha
    return None


def ref_sha(ref: str) -> str | None:
    result = subprocess.run(["git", "rev-parse", "--verify", "-q", ref], check=False, capture_output=True, text=True)
    return result.stdout.strip() or None


def pushed(sha: str) -> str:
    on_origin = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "origin/main"], check=False).returncode == 0
    return "pushed" if on_origin else "unpushed"


if __name__ == "__main__":
    refs = [ref for ref in ("main", "origin/main") if ref_sha(ref)]
    for name, sha in (("local", ref_sha("main")), ("dev", ref_sha("origin/main")),
                      ("release", latest_release(*refs) if refs else None), ("space", ref_sha("space/main"))):
        print(f"{name}: {sha} {version_at(sha)} {pushed(sha)}" if sha else f"{name}: none")
