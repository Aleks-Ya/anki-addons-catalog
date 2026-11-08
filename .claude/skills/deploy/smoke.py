"""Smoke-test the Space after /deploy: health and version, the main pages, the MCP server and optionally AI search.

Usage: uv run python smoke.py <target-sha> <production|staging> [--page <path>[=<text>]]... [--ask <question>]
Run from the repository root. Reads the stored HF token (staging is private) and the admin password from `.env`
itself, so no secret appears in a command or in the output. Prints one "PASS|FAIL <check>: <detail>" line per check
and exits 0 when all pass, 1 otherwise.
--page also checks a page the deployed commit changed: it must return 200 and, with `=<text>`, contain the text.
--ask asks the AI search one question as the admin, which skips Turnstile and the rate limit (the daily budget still
applies). It costs a few cents of Claude credits.
"""
import argparse
import base64
import json
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from space import Target, get_target, git, hf_token, version_at

ADDON = 1374772155  # Image Occlusion Enhanced
Check = tuple[bool, str]


def fetch(url: str, headers: dict[str, str], timeout: int = 60) -> tuple[int, str]:
    """The status and body; status 0 when there is no HTTP response."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, str(e)


def health(status: int, body: str, version: str) -> Check:
    try:
        data = json.loads(body)
    except ValueError:
        return False, f"HTTP {status}, not JSON: {body[:200]}"
    if data.get("status") != "ok" or data.get("version") != version:
        return False, f"HTTP {status}, {data}, expected version {version}"
    return True, f"version {version}"


def contains(status: int, body: str, text: str, what: str) -> Check:
    count = body.count(text)
    return status == 200 and count > 0, f"HTTP {status}, {count} {what}"


def ok_status(status: int, _body: str) -> Check:
    return status == 200, f"HTTP {status}"


def locked_version(lock: str, package: str = "anki-addons-mcp") -> str | None:
    return next((p["version"] for p in tomllib.loads(lock)["package"] if p["name"] == package), None)


def about(status: int, body: str, version: str | None) -> Check:
    expected = f"MCP server</a> (v{version})"
    if status != 200 or expected not in body:
        return False, f"HTTP {status}, no '{expected}' (an old image?)"
    return True, f"shows v{version}"


def mcp_log(lines: list[str]) -> Check:
    """Checks the run log since the last start: the MCP server must run in-process."""
    starts = [i for i, line in enumerate(lines) if line.startswith("===== Application Startup")]
    lines = lines[starts[-1]:] if starts else lines
    server = next((line.split("MCP server: ", 1)[1] for line in lines if "MCP server: " in line), None)
    notes = ["dataset loaded" if any("Dataset loaded" in line for line in lines) else "dataset not loaded yet"]
    unavailable = sum("Catalog unavailable" in line for line in lines)
    if unavailable:
        notes.append(f"{unavailable} 'Catalog unavailable' warnings")
    if server is None:
        return False, "no 'MCP server:' line in the log since the last start"
    if server != "in-process":
        return False, f"remote MCP server {server}: the Space variable ANKI_CATALOG_MCP_URL is set"
    return True, ", ".join(["in-process", *notes])


def parse_sse(text: str) -> list[tuple[str, Any]]:
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields.get("data", "null"))))
    return events


def answer(events: list[tuple[str, Any]], token_var: str) -> Check:
    names = [name for name, _ in events if name != "text"]
    if names == ["verify"]:
        return False, f"asked for Turnstile: the local {token_var} is not the Space's ANKI_CATALOG_ADMIN_TOKEN"
    errors = [data for name, data in events if name == "error"]
    if errors:
        return False, f"error: {errors[0]}"
    cards = next((data for name, data in events if name == "addons"), None)
    if names[-3:] != ["answer", "addons", "done"] or not cards or not cards["count"]:
        return False, f"events end with {names[-4:]}, {cards['count'] if cards else 0} cards"
    summaries = cards["html"].count('class="summary"')
    return True, f"{cards['count']} cards, {summaries} with a summary"


def env_value(text: str, name: str) -> str | None:
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip("'\"")
    return None


def run_log(space: str) -> list[str]:
    result = subprocess.run(["uv", "run", "hf", "spaces", "logs", space],
                            capture_output=True, text=True, timeout=120, check=True)
    return result.stdout.splitlines()


def checks(sha: str, space: Target, pages: list[str], question: str | None) -> list[tuple[str, Check]]:
    headers = {}
    if space.private:
        headers["X-HF-Authorization"] = f"Bearer {hf_token()}"  # the Space proxy; Authorization stays for the admin

    def get(path: str, timeout: int = 60) -> tuple[int, str]:
        return fetch(space.site + path, headers, timeout)

    version = version_at(sha)
    results = [("healthz", health(*get("/healthz"), version))]
    if space.domain:
        results.append(("domain healthz", health(*fetch(space.domain + "/healthz", {}), version)))
    results += [
        ("home", contains(*get("/"), "Highest rated", "'Highest rated'")),
        ("search", contains(*get("/search?q=image+occlusion"), 'class="card"', "cards")),
        ("addon page", ok_status(*get(f"/addon/{ADDON}"))),
        ("top page", ok_status(*get("/top/rating"))),
    ]
    mcp = locked_version(git("show", f"{sha}:uv.lock"))
    results.append((f"about: anki-addons-mcp {mcp}", about(*get("/about"), mcp)))
    try:
        results.append(("MCP server log", mcp_log(run_log(space.space))))
    except (subprocess.SubprocessError, OSError) as e:
        results.append(("MCP server log", (False, f"cannot read the run log: {e}")))
    for spec in pages:
        path, _, text = spec.partition("=")
        results.append((f"page {path}", contains(*get(path), text, repr(text)) if text else ok_status(*get(path))))
    if question:
        results.append((f"ask {question!r}", ask(space, headers, question)))
    return results


def ask(space: Target, headers: dict[str, str], question: str) -> Check:
    with open(".env") as f:
        password = env_value(f.read(), space.admin_token_var)
    if not password:
        return False, f"no {space.admin_token_var} in .env"
    login = base64.b64encode(f"admin:{password}".encode()).decode()
    status, body = fetch(f"{space.site}/api/ask?q={urllib.parse.quote_plus(question)}",
                         headers | {"Authorization": f"Basic {login}"}, timeout=180)
    if status != 200:
        return False, f"HTTP {status}: {body[:200]}"
    return answer(parse_sse(body), space.admin_token_var)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sha")
    parser.add_argument("target", choices=["production", "staging"])
    parser.add_argument("--page", action="append", default=[])
    parser.add_argument("--ask")
    args = parser.parse_args()
    results = checks(args.sha, get_target(args.target), args.page, args.ask)
    for name, (ok, detail) in results:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
    return 0 if all(ok for _, (ok, _) in results) else 1


if __name__ == "__main__":
    sys.exit(main())
