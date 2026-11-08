"""Print the commits /deploy offers: the development heads of main and the latest release on them.

local: the tip of the local main branch, which may not be pushed yet.
dev: the tip of origin/main (usually a .dev0 version right after /release).
release: the newest commit on main or origin/main whose __version__ is a plain X.Y.Z (the /release commit; it may be
unpushed).
space: what the Space remote's main is now.
running: the stage and the sha the Space runs, from its runtime API.
Usage: uv run python candidates.py <production|staging>
Each commit line is "<name>: <sha> <version> <pushed|tagged|unpushed>", or "<name>: none". pushed means the commit is
on origin/main; tagged means it is not, but a tag on GitHub points at it (the /release commit before `/push`). Run from
the repository root after `git fetch --multiple origin <remote>`.
"""
import re
import sys

from space import VERSION_FILE, get_target, git, is_ancestor, ref_sha, runtime, version_at

RELEASE = re.compile(r"\d+\.\d+\.\d+")


def latest_release(*refs: str) -> str | None:
    for sha in git("log", "--format=%H", *refs, "--", VERSION_FILE).splitlines():
        if RELEASE.fullmatch(version_at(sha)):
            return sha
    return None


def tagged_on_origin() -> set[str]:
    """The shas that tags on origin point at, with annotated tags also peeled to their commits (the `^{}` lines)."""
    return {line.split()[0] for line in git("ls-remote", "--tags", "origin").splitlines()}


def push_state(sha: str, tagged: set[str]) -> str:
    return "pushed" if is_ancestor(sha, "origin/main") else "tagged" if sha in tagged else "unpushed"


if __name__ == "__main__":
    space = get_target(sys.argv[1])
    refs = [ref for ref in ("main", "origin/main") if ref_sha(ref)]
    tagged = tagged_on_origin()
    for name, sha in (("local", ref_sha("main")), ("dev", ref_sha("origin/main")),
                      ("release", latest_release(*refs) if refs else None), ("space", ref_sha(f"{space.remote}/main"))):
        print(f"{name}: {sha} {version_at(sha)} {push_state(sha, tagged)}" if sha else f"{name}: none")
    print("running: {} {}".format(*runtime(space.space)))
