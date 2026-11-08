"""Find the Unit-tests run for <sha> and watch it to the end.

Usage: python3 wait_ci.py <sha>
The run appears a few seconds after the push: the script polls `gh run list` every 5 s for up to 2 min, prints the
run's id and URL, then watches it with `gh run watch --exit-status`. Exits with the watch's code (0 when the run
passed), or 2 when no run appears. On a failure, read the log with `gh run view <id> --log-failed`.
"""
import json
import subprocess
import sys
import time

WORKFLOW = "unit-tests.yml"
INTERVAL_SECONDS = 5
ATTEMPTS = 24


def find_run(sha: str) -> dict[str, str] | None:
    runs = json.loads(subprocess.run(["gh", "run", "list", "--commit", sha, "--workflow", WORKFLOW, "--limit", "1",
                                      "--json", "databaseId,url"], check=True, capture_output=True, text=True).stdout)
    return runs[0] if runs else None


def main(sha: str) -> int:
    for attempt in range(ATTEMPTS):
        run = find_run(sha)
        if run:
            print(f"run {run['databaseId']}: {run['url']}", flush=True)
            return subprocess.run(["gh", "run", "watch", str(run["databaseId"]), "--exit-status", "--compact",
                                   "--interval", "30"], check=False).returncode
        if attempt < ATTEMPTS - 1:
            time.sleep(INTERVAL_SECONDS)
    print(f"No {WORKFLOW} run for {sha[:7]} after {ATTEMPTS * INTERVAL_SECONDS} s")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
