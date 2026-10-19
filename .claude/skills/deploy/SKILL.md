---
name: deploy
description: Deploy main to the HuggingFace Space and see it running — check that main is pushed and green, push it to the `space` remote, wait for the Space to rebuild on that commit, and smoke-test the live site. Use when the user says "deploy", "/deploy", or asks to update/redeploy the HuggingFace Space.
allowed-tools: Bash(git *) Bash(gh *) Bash(curl *) Bash(python3 *)
disable-model-invocation: true
---

# deploy

Deploy `main` to the HuggingFace Space (README-DEV.md → "Deploy to a HuggingFace Space") and verify that the
Space runs the pushed commit. This is the follow-on to `/push`: it deploys what is already on GitHub and green,
and does not commit or fix code itself. Work through the steps in order; stop and report if a step can't be
completed.

- Space: https://huggingface.co/spaces/Ya-Alex/anki-addons-catalog (git remote `space`)
- Site: `https://ya-alex-anki-addons-catalog.hf.space`, custom domain `https://www.anki-addons-catalog.com`,
  health check `/healthz`
- Runtime API (public, no token): `https://huggingface.co/api/spaces/Ya-Alex/anki-addons-catalog/runtime`

## 1. Preconditions

Confirm the current branch is `main` and the working tree is clean:

```bash
git rev-parse --abbrev-ref HEAD
git status --porcelain
```

If not on `main`, or there is **any** `git status` output, stop and report. Do not commit on the user's behalf.

Confirm `main` is pushed to GitHub and its CI is green; the Space must only get code that passed CI:

```bash
git fetch -q origin
git rev-parse HEAD origin/main
gh run list --branch main --commit "$(git rev-parse HEAD)" --workflow unit-tests.yml --limit 1
```

- If `HEAD` differs from `origin/main`, stop and tell the user to run `/push` first.
- If the Unit-tests run for `HEAD` is in progress, wait for it with `gh run watch <run-id> --exit-status`.
- If it failed, or there is no run, stop and tell the user to run `/push` first.

Confirm the remote `space` exists (`git remote get-url space`). If it is missing, stop and point the user to the
setup in README-DEV.md (`git remote add space https://huggingface.co/spaces/Ya-Alex/anki-addons-catalog`).

## 2. Check what the Space runs now

```bash
git fetch -q space
git rev-parse space/main
curl -s https://huggingface.co/api/spaces/Ya-Alex/anki-addons-catalog/runtime \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); print(r["stage"], r.get("sha"))'
```

- If `space/main` already equals `HEAD` and the runtime is `RUNNING` on that sha, nothing needs deploying: skip
  to step 5 to smoke-test and report.
- If `space/main` is **not** an ancestor of `HEAD` (`git merge-base --is-ancestor space/main HEAD` fails), the
  Space has commits that are not on `main` (e.g. edits made on huggingface.co). Stop and report; never
  force-push to the Space.

## 3. Push to the Space

```bash
git push space main
```

Git authenticates to huggingface.co with the HF token stored in its credential helper. If the push fails with an
authentication error (e.g. `could not read Username for 'https://huggingface.co'`), stop and tell the user to
store a token with write access to the Space (e.g. `hf auth login --add-to-git-credential`). If the push is
rejected for any other reason, stop and report.

## 4. Wait for the Space to build and start

Pushing triggers a Docker rebuild. Poll the runtime API every 20 s, for up to 15 min, until the Space runs the
pushed commit. Run the poll as a single `python3` command (no shell `for`/`sleep` loop, which needs extra
permission), with a Bash timeout of at least 960000 ms:

```bash
python3 -c '
import json, sys, time, urllib.request
url = "https://huggingface.co/api/spaces/Ya-Alex/anki-addons-catalog/runtime"
for _ in range(45):
    runtime = json.load(urllib.request.urlopen(url))
    stage, sha = runtime["stage"], runtime.get("sha")
    print(time.strftime("%H:%M:%S"), stage, sha, flush=True)
    if (stage == "RUNNING" and sha == sys.argv[1]) or stage.endswith("ERROR"):
        break
    time.sleep(20)
' "$(git rev-parse HEAD)"
```

- `BUILDING`, `RUNNING_BUILDING`, `APP_STARTING` (or the old sha still `RUNNING`): keep waiting.
- `RUNNING` with `sha` equal to `git rev-parse HEAD`: continue to step 5.
- `BUILD_ERROR`, `RUNTIME_ERROR` or `CONFIG_ERROR`: stop. Report the stage and point the user to the **Logs** tab
  of the Space page (build and container logs need a token to read through the API). Reproduce a build failure
  locally with `docker build .` if useful.
- Still not running the new sha after ~15 min: stop and report the last stage seen.

## 5. Smoke-test the live site

The checks are read-only and free. Never call `/api/ask`: each question costs Claude credits and is
gated by Turnstile.

```bash
SITE=https://ya-alex-anki-addons-catalog.hf.space
curl -s -m 60 "$SITE/healthz"
curl -s -m 60 https://www.anki-addons-catalog.com/healthz
curl -s -m 60 "$SITE/" | grep -c 'Highest rated'
curl -s -m 60 "$SITE/search?q=image+occlusion" | grep -c 'class="card"'
curl -s -m 60 -o /dev/null -w '%{http_code}\n' "$SITE/addon/1374772155"
curl -s -m 60 -o /dev/null -w '%{http_code}\n' "$SITE/top/rating"
```

- Both `/healthz` calls must return `{"status": "ok", "version": ...}` with the version in
  `src/anki_addons_catalog/__init__.py`. Development versions don't change on every commit, so the runtime sha
  (step 4) is what proves the new commit is live, not the version.
- The home page must contain "Highest rated", and the search must return at least one card. Both pages read from
  the MCP Space, so a failure here can come from the MCP Space instead.
- The add-on and top pages must return `200`.
- If the deployed commit changed a page, also fetch that page and check the change is visible.

If a check fails, report the output and point the user to the **Logs** tab of the Space page.

## 6. Check the MCP dependency

Production talks to the live MCP Space, but the tests ran against the `anki-addons-mcp` commit pinned in
`pyproject.toml` (`[tool.uv.sources]`, `rev = ...`). Compare them:

```bash
grep -o 'rev = "[0-9a-f]*"' pyproject.toml
curl -s https://huggingface.co/api/spaces/Ya-Alex/anki-addons-mcp/runtime \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); print(r["stage"], r.get("sha"))'
```

If the MCP Space is not `RUNNING`, or runs a different commit than the pin, warn the user. Don't fail the deploy
over it: the MCP Space and its pin are updated separately.

## Done

Report the deployed commit SHA (and the previous one the Space ran), the runtime stage, the `/healthz` version, the
smoke-test results and the MCP pin check, or the first step that failed and why.
