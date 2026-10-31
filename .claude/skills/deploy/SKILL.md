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
`X.Y.Z`) and `space` (the Space's `main` now). `pushed` means the
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

### Check that the image was really rebuilt

HF's Docker layer cache can reuse the old image: every step of the build log is `CACHED`, even `COPY src`, yet the
runtime reports the new sha as `RUNNING` while the old code serves. Check the build log, where `PREVIOUS` is the
`space/main` sha from step 2 (what the Space ran before the push):

```bash
python3 .claude/skills/deploy/check_build.py <TARGET> <PREVIOUS>
```

It exits 0 for a fresh build of `TARGET`. It exits 1 when the latest build is for another commit, or when a `COPY`
step was `CACHED` although the files it copies changed between `PREVIOUS` and `TARGET`, and prints why. It exits 2
when it can't read the log (it needs the stored HF token, like step 6). Skip this check when step 2 found nothing
to deploy.

On exit 1, ask the user with AskUserQuestion whether to run a factory rebuild (same commit, no layer cache; the
site is down for about a minute). Only after they confirm:

```bash
uv run python -c "from huggingface_hub import HfApi; HfApi().restart_space('Ya-Alex/anki-addons-catalog', factory_reboot=True)"
python3 .claude/skills/deploy/wait_space.py --restarted <TARGET>
python3 .claude/skills/deploy/check_build.py <TARGET> <PREVIOUS>
```

`--restarted` waits for the Space to leave `RUNNING` first, since the old container already reports `TARGET`. If
the check still fails, or the user declines, stop and report. On exit 2, report it and rely on the version checks
in steps 5 and 6.

## 5. Smoke-test the live site

The page checks are read-only and free. The AI search check asks Claude one question, which costs a few cents of
Claude credits; the user allows it for smoke testing.

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
  commit, so the runtime sha and the build check (step 4) prove the new commit is live, not the version.
- The home page must contain "Highest rated", and the search must return at least one card. Both pages read from
  the in-process MCP server, which loads the dataset from the HF Hub on start, so the first page can take seconds.
- The add-on and top pages must return `200`.
- If the deployed commit changed a page, also fetch that page and check the change is visible.

Then ask the AI search one question. The admin login (password `ANKI_CATALOG_ADMIN_TOKEN` from the local `.env`)
skips Turnstile and the rate limit; the daily budget still applies. Don't print the token.

```bash
TOKEN=$(sed -n 's/^ANKI_CATALOG_ADMIN_TOKEN=//p' .env)
curl -sN -m 180 -u "admin:$TOKEN" "$SITE/api/ask?q=Maintained+forks+of+Review+Heatmap" \
  | python3 -c 'import sys,json
events = [(e.split("\n")[0][7:], json.loads(e.split("data: ", 1)[1])) for e in sys.stdin.read().strip().split("\n\n")]
print([name for name, _ in events if name != "text"][-4:])
print(next((d["count"], d["html"].count("class=\"summary\"")) for name, d in events if name == "addons"))'
```

- The events must end with `answer`, `addons`, `done`, and the answer must show at least one card. The second
  line prints the number of cards and how many of them have a summary.
- A single `verify` event means the local token is not the Space's `ANKI_CATALOG_ADMIN_TOKEN`; an `error` event
  shows its message (budget spent, catalog unavailable). Report it; don't retry.
- Ask one question per deploy: answers are cached per question for the life of the container, so asking again
  tests nothing. If the deployed commit changed AI search, pick a question that exercises the change instead.

If a check fails, report the output and point the user to the **Logs** tab of the Space page.

## 6. Check the MCP server

The catalog runs the `anki-addons-mcp` version locked in `uv.lock` in-process, the one the tests ran against.
Report it, and check that the Space did not switch to a remote MCP server:

```bash
git show <TARGET>:uv.lock | grep -A1 '^name = "anki-addons-mcp"'
curl -s -m 60 "$SITE/about" | grep -o 'MCP server</a> (v[^)]*)'
uv run hf spaces logs Ya-Alex/anki-addons-catalog | grep -E 'MCP server:|Dataset loaded|Catalog unavailable' | head -5
```

The About page must show the locked version; another version means the Space serves an old image (see
"Check that the image was really rebuilt" in step 4). The log must say "MCP server: in-process". A URL there means
the Space variable `ANKI_CATALOG_MCP_URL` is set: warn the user, since the HF proxy answers requests from the catalog
Space to the MCP Space with HTTP 429 in bursts (README-DEV, "MCP server").

## Done

Report the deployed version and commit SHA (and the previous ones the Space ran), the runtime stage, the build check
(and any factory rebuild), the `/healthz` version, the smoke-test results and the MCP server check, or the first step
that failed and why.
