---
name: push
description: Push the main branch and see it through green — verify a clean tree, upgrade deps and run ruff, mypy and pytest locally, push, wait for the GitHub Actions "Unit-tests" workflow and fix any failures, then review SonarCloud issues on the new code and fix them. Does not deploy; that is /deploy. Use when the user says "push", "/push", or asks to push and make sure CI/Sonar are clean.
allowed-tools: Bash(uv *) Bash(gh run *) Bash(gh api *) Bash(git *) Bash(curl *)
disable-model-invocation: true
---

# push

Push `main` and drive it to a fully green state: CI passing and no new SonarCloud issues. Work through the steps
in order; stop and report if a step can't be completed. This skill does not deploy: the HuggingFace Space is
updated only by `/deploy`.

## 1. Verify a clean working tree

```bash
git status --porcelain
git rev-parse --abbrev-ref HEAD
```

- If `git status` prints **anything**, stop. Do not push. Report the uncommitted files and ask whether to commit
  them (and how). Never commit on the user's behalf here unless they explicitly ask.
- If the branch is not `main`, stop and ask the user before pushing.

## 2. Upgrade dependencies and run checks locally

Run the same checks as CI (`.github/workflows/unit-tests.yml`) so failures are caught before pushing:

```bash
uv lock --upgrade && uv sync
uv run ruff check src tests
uv run mypy
uv run pytest
```

- If `uv lock --upgrade` changes `uv.lock`, that change must be committed: CI runs `uv sync --locked` and fails
  on a stale lock. Ask the user before committing it.
- `uv lock --upgrade` does not move `anki-addons-mcp`: it is pinned to a git commit in `pyproject.toml`
  (`[tool.uv.sources]`, `rev = ...`). Compare the pin with the MCP repo's `main`:
  ```bash
  gh api repos/Aleks-Ya/anki-addons-mcp/commits/main --jq '.sha + " " + (.commit.message|split("\n")[0])'
  ```
  If `main` is ahead of the pin, mention it and offer to bump the pin (edit `rev`, `uv lock -P anki-addons-mcp`,
  re-run the checks). Never bump it silently.
- If ruff, mypy or pytest **fails**, stop. Do not push. Fix the failures in the working tree, re-run the checks
  until green, and ask before committing the fix.

## 3. Push the main branch

```bash
git push origin main
```

If the push is rejected (e.g. remote is ahead), a force-push is allowed only when the user has explicitly asked for
it (e.g. "force push", "/push force"). Then use `git push --force-with-lease origin main`, never bare `--force`.
If the push is rejected and the user hasn't asked to force, stop and report the rejection.

## 4. Wait for GitHub Actions and check success

The push triggers the **Unit-tests** workflow (TruffleHog → Ruff → Mypy → PyTest → SonarCloud Scan). Find the run
for the pushed commit; it may take a few seconds to appear:

```bash
gh run list --commit "$(git rev-parse HEAD)" --workflow unit-tests.yml --limit 1 --json databaseId,status,url
```

Watch it to completion (blocks until it finishes; exits non-zero on failure):

```bash
gh run watch <run-id> --exit-status
```

If it **fails**, read the failing job with `gh run view <run-id> --log-failed`. Diagnose the failure (failing
test, ruff or mypy error, TruffleHog secret finding, stale lock, ...), fix it in the working tree, commit it as a
new commit (not `--amend`, never `--no-verify`), push again and repeat this step until the run is green. Report
what failed and what you changed.

## 5. Review SonarCloud and fix

The scan publishes to SonarCloud (project `Aleks-Ya_anki-addons-catalog`, org `aleks-ya`). The workflow does not
wait for the quality gate, so a green run does not mean Sonar is clean. After CI is green, read the report (the
API is readable anonymously):

```bash
curl -s 'https://sonarcloud.io/api/qualitygates/project_status?projectKey=Aleks-Ya_anki-addons-catalog' | python3 -m json.tool
curl -s 'https://sonarcloud.io/api/issues/search?componentKeys=Aleks-Ya_anki-addons-catalog&resolved=false&ps=100' | python3 -m json.tool
curl -s 'https://sonarcloud.io/api/hotspots/search?projectKey=Aleks-Ya_anki-addons-catalog&status=TO_REVIEW&ps=100' | python3 -m json.tool
```

Focus on issues and hotspots in the code just pushed (recent `creationDate`, or files in the diff). For each:

- Read the `rule`, `message`, `component` (file) and `line`, and fix the underlying code; don't just silence it.
- Suppress inline (`# NOSONAR` with a short reason) only for a genuine false positive, and say so. No local token
  can mark issues "Won't Fix" through the API, so the inline comment is what records the decision.
- If it's unclear whether to fix or ignore an issue, ask the user.
- Re-run the local checks before pushing a fix, then loop back through steps 4–5 until CI is green and the new
  code has no open issues.

If the API returns nothing usable, point the user to
https://sonarcloud.io/project/issues?id=Aleks-Ya_anki-addons-catalog&resolved=false

## Done

Report the pushed commit SHA, the CI result (first try, or what was fixed), the Sonar status (quality gate, and
clean or what was fixed/suppressed), and the run URL. End with: "Deploy with `/deploy`."
