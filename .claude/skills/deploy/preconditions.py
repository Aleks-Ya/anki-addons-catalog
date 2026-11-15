"""Check what /deploy needs before it picks a version: the Space remote, and a tree with nothing uncommitted.

Usage: uv run python preconditions.py <production|staging>
Run from the repository root. Prints one "PASS|FAIL <check>: <detail>" line per check. Exits 0 when all pass, 1 when
the Space remote is missing (stop), and 2 when only uncommitted changes fail: only commits can be deployed, so ask
whether to commit them first.
"""
import subprocess
import sys

from space import Target, get_target, git

Check = tuple[bool, str]


def remote(space: Target) -> Check:
    result = subprocess.run(["git", "remote", "get-url", space.remote], check=False, capture_output=True, text=True)
    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, f"add it with: git remote add {space.remote} https://huggingface.co/spaces/{space.space}"


def committed(status: str) -> Check:
    """From `git status --porcelain`: whether the tree is clean, else the uncommitted files."""
    return not status, ", ".join(line.strip() for line in status.splitlines()) or "clean tree"


def exit_code(remote_ok: bool, clean: bool) -> int:
    return 1 if not remote_ok else 0 if clean else 2


def main(name: str) -> int:
    space = get_target(name)
    results = [("remote", remote(space)), ("committed", committed(git("status", "--porcelain")))]
    for check, (ok, detail) in results:
        print(f"{'PASS' if ok else 'FAIL'} {check}: {detail}")
    return exit_code(results[0][1][0], results[1][1][0])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
