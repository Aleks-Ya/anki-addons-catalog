"""Wait until the HuggingFace Space runs the given commit, polling its public runtime API.

Usage: python3 wait_space.py <sha> [<space-id>]
Polls every 20 s for up to 15 min and prints each stage. Exits 0 when the Space is RUNNING on <sha>,
1 on a *_ERROR stage, 2 on timeout.
"""
import json
import sys
import time
import urllib.request

INTERVAL_SECONDS = 20
ATTEMPTS = 45


def runtime(space: str) -> tuple[str, str | None]:
    with urllib.request.urlopen(f"https://huggingface.co/api/spaces/{space}/runtime", timeout=30) as response:
        data = json.load(response)
    return data["stage"], data.get("sha")


def main(sha: str, space: str) -> int:
    for attempt in range(ATTEMPTS):
        stage, running_sha = runtime(space)
        print(time.strftime("%H:%M:%S"), stage, running_sha, flush=True)
        if stage == "RUNNING" and running_sha == sha:
            return 0
        if stage.endswith("ERROR"):
            return 1
        if attempt < ATTEMPTS - 1:
            time.sleep(INTERVAL_SECONDS)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Ya-Alex/anki-addons-catalog"))
