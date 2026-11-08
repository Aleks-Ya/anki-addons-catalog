"""Wait for SonarCloud to analyze <sha> on main, then print the quality gate and the open issues and hotspots.

Usage: python3 sonar.py <sha>
The project's main branch in SonarCloud is an empty `master`, so `main` is analyzed as a short-lived branch and every
query passes branch=main (without it the gate is NONE with 0 issues). The analysis lands about a minute after the CI
run finishes; the script polls every 15 s for up to 10 min. It prints the gate, then one line per open issue and per
hotspot to review, newest first: "<created> <kind> <rule> <file>:<line> <message>". The API is readable anonymously.
Exits 0 when the gate passes and nothing is open, 1 otherwise, 2 when no analysis of <sha> appears.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

PROJECT = "Aleks-Ya_anki-addons-catalog"
INTERVAL_SECONDS = 15
ATTEMPTS = 40


def api(path: str, **params: str) -> Any:
    url = f"https://sonarcloud.io/api/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def analyzed_sha(branches: dict[str, Any]) -> str | None:
    main = next((b for b in branches["branches"] if b["name"] == "main"), {})
    return main.get("commit", {}).get("sha")


def failed_conditions(status: dict[str, Any]) -> list[str]:
    return [f"{c['metricKey']} {c.get('actualValue')} (threshold {c['comparator']} {c.get('errorThreshold')})"
            for c in status["projectStatus"].get("conditions", []) if c["status"] != "OK"]


def finding(item: dict[str, Any], kind: str, rule: str) -> str:
    path = item["component"].split(":", 1)[-1]
    line = f":{item['line']}" if "line" in item else ""
    return f"{item['creationDate'][:10]} {kind} {rule} {path}{line} {item['message']}"


def findings(issues: dict[str, Any], hotspots: dict[str, Any]) -> list[str]:
    lines = [finding(i, i.get("severity", "issue"), i["rule"]) for i in issues["issues"]]
    lines += [finding(h, f"hotspot/{h.get('vulnerabilityProbability', '?')}", h["ruleKey"])
              for h in hotspots["hotspots"]]
    return sorted(lines, reverse=True)


def wait_for(sha: str) -> bool:
    for attempt in range(ATTEMPTS):
        analyzed = analyzed_sha(api("project_branches/list", project=PROJECT))
        print(time.strftime("%H:%M:%S"), "main analyzed at", analyzed, flush=True)
        if analyzed == sha:
            return True
        if attempt < ATTEMPTS - 1:
            time.sleep(INTERVAL_SECONDS)
    return False


def main(sha: str) -> int:
    if not wait_for(sha):
        print(f"No analysis of {sha[:7]} on main after {ATTEMPTS * INTERVAL_SECONDS // 60} min")
        return 2
    status = api("qualitygates/project_status", projectKey=PROJECT, branch="main")
    gate = status["projectStatus"]["status"]
    print(f"quality gate: {gate}")
    for condition in failed_conditions(status):
        print(f"  failed: {condition}")
    lines = findings(api("issues/search", componentKeys=PROJECT, branch="main", resolved="false", ps="500"),
                     api("hotspots/search", projectKey=PROJECT, branch="main", status="TO_REVIEW", ps="500"))
    print(f"open: {len(lines)}")
    for line in lines:
        print(line)
    return 0 if gate == "OK" and not lines else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
