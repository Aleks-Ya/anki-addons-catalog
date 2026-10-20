---
name: deploy
description: Deploy any version of main to the HuggingFace Space and see it running — suggest the development heads (local and pushed) and the latest release, ask which one to deploy, push it without running CI or local checks to the `space` remote, wait for the Space to rebuild on that commit, and smoke-test the live site. Use when the user says "deploy", "/deploy", or asks to update/redeploy the HuggingFace Space.
allowed-tools: Bash(git *) Bash(gh *) Bash(uv *) Bash(curl *) Bash(python3 *)
disable-model-invocation: true
---

# deploy

Deploy a version of `main` to the HuggingFace Space (README-DEV.md → "Deploy to a HuggingFace Space") and verify
that the Space runs the pushed commit. The user picks the version: usually the development head of `main` (local or
on GitHub) or the latest release (the commit `/release` made before switching to the next `.dev0` version), but any
commit can be deployed, pushed to GitHub or not. It deploys commits only and does not commit or fix code itself.
It runs no CI or local checks (lint, types, tests) before pushing: it just deploys the chosen commit.
Work through the steps in order; stop and report if a step can't be completed.

- Space: https://huggingface.co/spaces/Ya-Alex/anki-addons-catalog (git remote `space`)
- Site: `https://ya-alex-anki-addons-catalog.hf.space`, custom domain `https://www.anki-addons-catalog.com`,
  health check `/healthz`
- Runtime API (public, no token): `https://huggingface.co/api/spaces/Ya-Alex/anki-addons-catalog/runtime`

## 1. Preconditions

Only committed code is deployed. If `git status --porcelain` prints anything, mention that uncommitted changes
won't be deployed, but don't stop and don't commit on the user's behalf.

Confirm the remote `space` exists (`git remote get-url space`). If it is missing, stop and point the user to the
setup in README-DEV.md (`git remote add space https://huggingface.co/spaces/Ya-Alex/anki-addons-catalog`).

## 2. Pick the version to deploy

```bash
git fetch -q --multiple origin space
python3 .claude/skills/deploy/candidates.py
curl -s https://huggingface.co/api/spaces/Ya-Alex/anki-addons-catalog/runtime \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); print(r["stage"], r.get("sha"))'
```

The script prints `<name>: <sha> <version> <pushed|unpushed>` for `local` (the tip of the local `main`), `dev` (the
tip of `origin/main`), `release` (the newest commit on `main` or `origin/main` whose `__version__` is a plain
`X.Y.Z`; `/release` does not tag, so it may be untagged) and `space` (the Space's `main` now). `pushed` means the
commit is on `origin/main`. The curl prints the stage and sha the Space actually runs.

Use AskUserQuestion with what the Space runs in the question text, e.g. "The Space runs 0.3.1 (d6bb48b, RUNNING).
Which version to deploy?", and one option per candidate, with the exact version and short sha as the label and
whether it is pushed in the description:

- `0.4.0.dev0 (e5a1cbb)` (local): the latest local commit on `main`, not pushed to GitHub
- `0.4.0.dev0 (abc1234)` (dev): the latest commit on GitHub's `main`
- `0.3.1 (d6bb48b)` (release): the latest release

Don't mark a default. Drop a candidate that is `none`, and offer a commit once when several candidates are the same
commit (e.g. `local` and `dev` when `main` is pushed). If the user picks "Other", accept any commit
(`git rev-parse --verify -q <rev>^{commit}`); otherwise ask again. Call the chosen commit `TARGET` (full sha,
`git rev-parse <rev>^{commit}`) from here on.

- If `space/main` already equals `TARGET` and the runtime is `RUNNING` on that sha, nothing needs deploying: skip
  to step 5 to smoke-test and report.
- If `space/main` is **not** an ancestor of `TARGET` (`git merge-base --is-ancestor space/main <TARGET>` fails),
  the push in step 3 must be forced. Check whether `space/main` is on `main` or `origin/main`
  (`git merge-base --is-ancestor space/main main`, same for `origin/main`):
  - If it is, `TARGET` is a rollback or a different branch of history (e.g. the release when the Space runs a later
    dev commit). List what the Space would lose (`git log --oneline <TARGET>..space/main`) and ask the user to
    confirm with AskUserQuestion; force-push in step 3 only after they confirm.
  - If it is not, the Space has commits that exist nowhere else (e.g. edits made on huggingface.co). Stop and
    report them; never overwrite them.

## 3. Push to the Space

```bash
git push space <TARGET>:refs/heads/main
```

For a rollback the user confirmed in step 2, force the push, but only over the commit you checked:

```bash
git push --force-with-lease=refs/heads/main:<space/main sha> space <TARGET>:refs/heads/main
```

Git authenticates to huggingface.co with the HF token stored in its credential helper. If the push fails with an
authentication error (e.g. `could not read Username for 'https://huggingface.co'`), stop and tell the user to
store a token with write access to the Space (e.g. `hf auth login --add-to-git-credential`). If the push is
rejected for any other reason, stop and report.

## 4. Wait for the Space to build and start

Pushing triggers a Docker rebuild. Wait until the Space runs the pushed commit, with a Bash timeout of at least
960000 ms. The script polls the runtime API every 20 s for up to 15 min and prints each stage:

```bash
python3 .claude/skills/deploy/wait_space.py <TARGET>
```

It exits 0 when the Space is `RUNNING` on that sha, 1 on an error stage and 2 on timeout.

- `BUILDING`, `RUNNING_BUILDING`, `APP_STARTING` (or the old sha still `RUNNING`): keep waiting.
- `RUNNING` with `sha` equal to `TARGET`: continue to step 5.
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

- Both `/healthz` calls must return `{"status": "ok", "version": ...}` with the version of
  `TARGET` (`git show <TARGET>:src/anki_addons_catalog/__init__.py`). Development versions don't change on every
  commit, so the runtime sha (step 4) is what proves the new commit is live, not the version.
- The home page must contain "Highest rated", and the search must return at least one card. Both pages read from
  the MCP Space, so a failure here can come from the MCP Space instead.
- The add-on and top pages must return `200`.
- If the deployed commit changed a page, also fetch that page and check the change is visible.

If a check fails, report the output and point the user to the **Logs** tab of the Space page.

## 6. Check the MCP dependency

Production talks to the live MCP Space, but the tests ran against the `anki-addons-mcp` commit pinned in
`pyproject.toml` (`[tool.uv.sources]`, `rev = ...`). Compare them:

```bash
git show <TARGET>:pyproject.toml | grep -o 'rev = "[0-9a-f]*"'
curl -s https://huggingface.co/api/spaces/Ya-Alex/anki-addons-mcp/runtime \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); print(r["stage"], r.get("sha"))'
```

If the MCP Space is not `RUNNING`, or runs a different commit than the pin, warn the user. Don't fail the deploy
over it: the MCP Space and its pin are updated separately.

## Done

Report the deployed version and commit SHA (and the previous ones the Space ran), the runtime stage, the `/healthz` version, the
smoke-test results and the MCP pin check, or the first step that failed and why.
