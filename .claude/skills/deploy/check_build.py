"""Check that the Space's latest build really built <target>, not a stale image from HF's layer cache.

Usage: python3 check_build.py <target-sha> <previous-sha> [<space-id>]
Reads the build log (`hf spaces logs --build`, the stored HF token) and fails when the build is not for <target>,
or when a COPY step of the Dockerfile was CACHED although the files it copies changed between <previous> (the
commit the Space ran before the push) and <target>. HF has reused the old image that way while reporting the new
sha as running. Exits 0 when the build is fresh, 1 when it is stale or for another commit, 2 when the log can't be
read.
"""
import re
import subprocess
import sys
from itertools import pairwise

HEADER = re.compile(r"^===== Build Queued at .* / Commit SHA: (\w+) =====$")
COPY = re.compile(r"^--> COPY (?!--from)(.+) \S+$")  # `COPY <sources...> <dest>`, not `COPY --from=<image>`


def build_log(space: str) -> list[str]:
    result = subprocess.run(["uv", "run", "hf", "spaces", "logs", "--build", space],
                            capture_output=True, text=True, timeout=120, check=True)
    return result.stdout.splitlines()


def changed(previous: str, target: str, paths: list[str]) -> bool:
    return subprocess.run(["git", "diff", "--quiet", previous, target, "--", *paths], check=False).returncode != 0


def check(lines: list[str], target: str, previous: str) -> list[str]:
    """The problems found in the log of the latest build; empty when it is a fresh build of `target`."""
    starts = [i for i, line in enumerate(lines) if HEADER.match(line.strip())]
    if not starts:
        return ["no build found in the log"]
    built = HEADER.match(lines[starts[-1]].strip()).group(1)  # type: ignore[union-attr]
    if not target.startswith(built):
        return [f"the latest build is for {built}, not {target[:7]}"]
    build = [line.strip() for line in lines[starts[-1] + 1:]]
    problems = []
    for step, status in pairwise(build):
        copy = COPY.match(step)
        if copy and status == "CACHED" and changed(previous, target, copy.group(1).split()):
            problems.append(f"'{step[4:]}' was CACHED although {copy.group(1)} changed since {previous[:7]}")
    return problems


def main(target: str, previous: str, space: str) -> int:
    try:
        lines = build_log(space)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"Cannot read the build log: {e}")
        return 2
    problems = check(lines, target, previous)
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"Fresh build of {target[:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "Ya-Alex/anki-addons-catalog"))
