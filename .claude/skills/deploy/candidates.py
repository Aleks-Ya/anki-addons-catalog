"""Print the commits /deploy offers: the development head of origin/main and the latest release on it.

dev: the tip of origin/main (usually a .dev0 version right after /release).
release: the newest commit on origin/main whose __version__ is a plain X.Y.Z (the /release commit; it may be untagged).
space: what the `space` remote's main is now.
Each line is "<name>: <sha> <version>", or "<name>: none". Run from the repository root after `git fetch origin space`.
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


def latest_release(ref: str) -> str | None:
    for sha in git("log", "--format=%H", ref, "--", VERSION_FILE).splitlines():
        if RELEASE.fullmatch(version_at(sha)):
            return sha
    return None


def ref_sha(ref: str) -> str | None:
    result = subprocess.run(["git", "rev-parse", "--verify", "-q", ref], check=False, capture_output=True, text=True)
    return result.stdout.strip() or None


if __name__ == "__main__":
    for name, sha in (("dev", ref_sha("origin/main")), ("release", latest_release("origin/main")),
                      ("space", ref_sha("space/main"))):
        print(f"{name}: {sha} {version_at(sha)}" if sha else f"{name}: none")
