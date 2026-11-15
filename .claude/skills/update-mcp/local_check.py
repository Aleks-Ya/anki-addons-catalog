"""Run the app locally on the upgraded MCP server and check it with the real dataset and, optionally, the real AI.

Usage: uv run python .claude/skills/update-mcp/local_check.py <target> [--page <path>[=<text>]]... [--ask <question>]...
                                                              [--log <file>]
Run from the repository root, after pin.py. Starts the app on a free local port with the MCP server in-process (its
log goes to --log), waits up to 10 minutes for "Dataset loaded" (the server downloads the target's dataset), then
prints one "PASS|FAIL <check>: <detail>" line per check: /healthz, the About page shows anki-addons-mcp <target>, the
home, search and addon pages, every --page (200 and, with =<text>, the text), and every --ask question asked as the
admin (password ANKI_CATALOG_ADMIN_TOKEN from .env). Then "cost: ..." lines from /admin/questions.jsonl and the total.
It always stops the app. At most 3 --ask: each costs a few cents of Claude credits, and more need the user's OK.
Exits 0 when all checks pass, 1 otherwise.
"""
import argparse
import base64
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy"))
from mcp_repo import Check
from smoke import about, answer, contains, env_value, fetch, health, ok_status, parse_sse

MAX_QUESTIONS = 3
ADDON = 1374772155  # Image Occlusion Enhanced
TOKEN_VAR = "ANKI_CATALOG_ADMIN_TOKEN"
READY = "Dataset loaded"
FAILED = ("Warm-up failed", "Traceback")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def app_version() -> str:
    match = re.search(r'__version__ = "([^"]+)"', Path("src/anki_addons_catalog/__init__.py").read_text())
    return match.group(1) if match else "?"


def startup(log: str) -> str | None:
    """"ready", "failed" or None (still starting), from the app's log so far."""
    if READY in log:
        return "ready"
    if any(marker in log for marker in FAILED):
        return "failed"
    return None


def in_process(log: str) -> Check:
    server = next((line.split("MCP server: ", 1)[1] for line in log.splitlines() if "MCP server: " in line), None)
    return server == "in-process", f"MCP server: {server}"


def costs(jsonl: str) -> tuple[list[str], float]:
    """One line per question the app logged (outcome, cost and query) and the total cost in USD."""
    questions = [json.loads(line) for line in jsonl.splitlines() if line.strip()]
    lines = [f"cost: ${q.get('cost_usd') or 0:.4f} {q.get('outcome')} {q.get('query')!r}" for q in questions]
    return lines, sum(q.get("cost_usd") or 0 for q in questions)


def wait_ready(process: subprocess.Popen[bytes], log_file: Path, timeout: float = 600) -> Check:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = startup(log_file.read_text(errors="replace"))
        if state == "ready":
            return True, "dataset loaded"
        if state == "failed" or process.poll() is not None:
            return False, f"the app failed to start (exit {process.poll()}); see {log_file}"
        time.sleep(5)
    return False, f"no '{READY}' after {timeout:.0f} s; see {log_file}"


def checks(site: str, target: str, pages: list[str], questions: list[str], auth: dict[str, str],
           log: str) -> list[tuple[str, Check]]:
    def get(path: str, headers: dict[str, str] | None = None, timeout: int = 60) -> tuple[int, str]:
        return fetch(site + path, headers or {}, timeout)

    results = [("in-process", in_process(log)),
               ("healthz", health(*get("/healthz"), app_version())),
               (f"about: anki-addons-mcp {target}", about(*get("/about"), target)),
               ("home", contains(*get("/"), "Highest rated", "'Highest rated'")),
               ("search", contains(*get("/search?q=image+occlusion"), 'class="card"', "cards")),
               ("addon page", ok_status(*get(f"/addon/{ADDON}")))]
    for spec in pages:
        path, _, text = spec.partition("=")
        results.append((f"page {path}", contains(*get(path), text, repr(text)) if text else ok_status(*get(path))))
    for question in questions:
        status, body = get(f"/api/ask?q={urllib.parse.quote_plus(question)}", auth, timeout=180)
        result: Check = answer(parse_sse(body), TOKEN_VAR) if status == 200 else (False, f"HTTP {status}: {body[:200]}")
        results.append((f"ask {question!r}", result))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--page", action="append", default=[])
    parser.add_argument("--ask", action="append", default=[])
    parser.add_argument("--log", default=str(Path(tempfile.gettempdir()) / "update-mcp-app.log"))
    args = parser.parse_args()
    if len(args.ask) > MAX_QUESTIONS:
        print(f"FAIL ask: {len(args.ask)} questions; at most {MAX_QUESTIONS} without asking the user")
        return 1
    auth: dict[str, Any] = {}
    if args.ask:
        password = env_value(Path(".env").read_text(), TOKEN_VAR) if Path(".env").exists() else None
        if not password:
            print(f"FAIL ask: no {TOKEN_VAR} in .env")
            return 1
        auth = {"Authorization": "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()}
    port, log_file = free_port(), Path(args.log)
    env = {**os.environ, "ANKI_CATALOG_MCP_URL": ""}  # the MCP server in-process, as in production
    with log_file.open("wb") as log:
        process = subprocess.Popen(["uv", "run", "anki-addons-catalog", "--port", str(port)], stdout=log,
                                   stderr=subprocess.STDOUT, env=env, start_new_session=True)
    print(f"app: http://127.0.0.1:{port}, log {log_file}")
    try:
        ready = wait_ready(process, log_file)
        results = [("startup", ready)]
        if ready[0]:
            site = f"http://127.0.0.1:{port}"
            results += checks(site, args.target, args.page, args.ask, auth, log_file.read_text(errors="replace"))
        ok = all(ok for _, (ok, _) in results)
        for name, (passed, detail) in results:
            print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")
        if args.ask and ready[0]:
            status, body = fetch(f"http://127.0.0.1:{port}/admin/questions.jsonl", auth)
            lines, total = costs(body) if status == 200 else ([f"cost: cannot read the question log (HTTP {status})"], 0.0)
            print("\n".join([*lines, f"cost total: ${total:.4f}"]))
        return 0 if ok else 1
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)


if __name__ == "__main__":
    sys.exit(main())
