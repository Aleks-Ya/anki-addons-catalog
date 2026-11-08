"""Wait until the HuggingFace Space runs the given commit, polling its runtime API with the stored HF token, which a
private Space needs.

Usage: uv run python wait_space.py [--restarted] <sha> <production|staging>
Polls every 20 s for up to 15 min and prints each stage. Exits 0 when the Space is RUNNING on <sha>,
1 on a *_ERROR stage, 2 on timeout. With --restarted (after a factory rebuild of the commit already running), the
Space must first leave RUNNING, so the old container doesn't count.
"""
import sys
import time

from space import get_target, runtime

INTERVAL_SECONDS = 20
ATTEMPTS = 45


def main(sha: str, space: str, restarted: bool = False) -> int:
    left_running = not restarted
    for attempt in range(ATTEMPTS):
        stage, running_sha = runtime(space)
        print(time.strftime("%H:%M:%S"), stage, running_sha, flush=True)
        left_running = left_running or stage != "RUNNING"
        if stage == "RUNNING" and running_sha == sha and left_running:
            return 0
        if stage.endswith("ERROR"):
            return 1
        if attempt < ATTEMPTS - 1:
            time.sleep(INTERVAL_SECONDS)
    return 2


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--restarted"]
    sys.exit(main(args[0], get_target(args[1]).space, "--restarted" in sys.argv))
