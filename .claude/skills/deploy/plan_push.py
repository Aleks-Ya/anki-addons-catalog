"""Work out how /deploy pushes <rev> to the Space: not at all, a plain push, a forced rollback, or not safely.

Usage: uv run python plan_push.py <rev> <production|staging>
Run from the repository root after `git fetch --multiple origin <remote>`. Prints the target, what the Space remote
has and runs, and a `push:` line:
- none: the Space remote already has <rev> and runs it; nothing to deploy.
- push: <rev> contains the Space remote's main; push it as it is.
- rollback: <rev> doesn't contain it, but the Space's commit is known here (on production: on main or origin/main; on
  staging: on any local or origin branch, since staging can run a feature branch). The push must be forced; the
  commits the Space would lose follow.
- foreign: the Space has commits that exist nowhere else (e.g. edits made on huggingface.co); never overwrite them.
For push and rollback, a `command:` line gives the exact git push to run.
"""
import sys

from space import Target, get_target, git, is_ancestor, ref_sha, runtime, version_at


def decide(target: str, remote: str | None, stage: str, running: str | None, fast_forward: bool, known: bool) -> str:
    if remote == target and stage == "RUNNING" and running == target:
        return "none"
    if remote is None or fast_forward:
        return "push"
    return "rollback" if known else "foreign"


def known(remote_sha: str, staging: bool) -> bool:
    if not staging:
        return any(is_ancestor(remote_sha, ref) for ref in ("main", "origin/main") if ref_sha(ref))
    branches = git("branch", "--all", "--contains", remote_sha, "--format=%(refname)").splitlines()
    return any(ref.startswith(("refs/heads/", "refs/remotes/origin/")) for ref in branches)


def command(mode: str, target: str, remote_sha: str | None, space: Target) -> str:
    lease = f"--force-with-lease=refs/heads/main:{remote_sha} " if mode == "rollback" else ""
    return f"git push {lease}{space.remote} {target}:refs/heads/main"


def main(rev: str, name: str) -> int:
    space = get_target(name)
    target = ref_sha(rev)
    if not target:
        print(f"Not a commit: {rev}")
        return 1
    remote_sha = ref_sha(f"{space.remote}/main")
    stage, running = runtime(space.space)
    fast_forward = remote_sha is not None and is_ancestor(remote_sha, target)
    mode = decide(target, remote_sha, stage, running, fast_forward,
                  remote_sha is not None and not fast_forward and known(remote_sha, name == "staging"))
    print(f"target: {target} {version_at(target)}")
    print(f"space: {remote_sha or 'none'}")
    print(f"running: {stage} {running}")
    print(f"push: {mode}")
    if mode in ("push", "rollback"):
        print(f"command: {command(mode, target, remote_sha, space)}")
    if mode == "rollback":
        print("the Space would lose:")
        print(git("log", "--oneline", f"{target}..{remote_sha}"))
    if mode == "foreign":
        print("commits only on the Space:")
        print(git("log", "--oneline", str(remote_sha), "--not", "--branches", "--remotes=origin"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
