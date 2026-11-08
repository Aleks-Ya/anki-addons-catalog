---
name: deploy
description: Deploy any version of main to the production HuggingFace Space or the private staging Space and see it running — ask which environment to deploy to (unless the argument `production` or `staging` names it), suggest the development heads (local and pushed) and the latest release, ask which one to deploy, push it without running CI or local checks to the Space's remote, wait for the Space to rebuild on that commit, and smoke-test the live site. Use when the user says "deploy", "/deploy", "/deploy staging", or asks to update/redeploy the HuggingFace Space.
allowed-tools: Bash(git *) Bash(uv *)
disable-model-invocation: true
---

# deploy

Deploy a version of `main` to the HuggingFace Space (README-DEV.md → "Deploy to a HuggingFace Space") and verify
that the Space runs the pushed commit. The user picks the version: usually the development head of `main` (local or
on GitHub) or the latest release (the commit `/release` made before switching to the next `.dev0` version), but any
commit can be deployed, pushed to GitHub or not. It deploys commits only and does not commit or fix code itself.
It runs no CI or local checks (lint, types, tests) before pushing: it just deploys the chosen commit.
Work through the steps in order; stop and report if a step can't be completed.

If the argument is `production` or `staging`, that is the target. Otherwise, before step 1, use AskUserQuestion to
ask which environment to deploy to, with the options `Production` (the public site) and `Staging` (the private test
Space). Don't mark a default. Use `production` or `staging` as `ENV`, and the target's values below as `REMOTE` and
`SPACE`, in every step. The scripts take `ENV` and know the rest (`.claude/skills/deploy/space.py`), including the HF
token a request to the private staging Space needs and the admin password in `.env`. Run them from the repository root.

| | Production | Staging |
|---|---|---|
| `REMOTE` | `space` | `space-staging` |
| `SPACE` | `Ya-Alex/anki-addons-catalog` | `Ya-Alex/anki-addons-catalog-staging` |
| Site | `https://ya-alex-anki-addons-catalog.hf.space` | `https://ya-alex-anki-addons-catalog-staging.hf.space` |
| Custom domain | `https://www.anki-addons-catalog.com` | none |
| Visibility | public | private: requests need the HF token |

The Space page is `https://huggingface.co/spaces/<SPACE>`.

## 1. Preconditions

Only committed code is deployed. If `git status --porcelain` prints anything, mention that uncommitted changes
won't be deployed, but don't stop and don't commit on the user's behalf.

Confirm the remote exists (`git remote get-url <REMOTE>`). If it is missing, stop and point the user to the
setup in README-DEV.md (`git remote add <REMOTE> https://huggingface.co/spaces/<SPACE>`).

## 2. Pick the version to deploy

```bash
git fetch -q --multiple origin <REMOTE>
uv run python .claude/skills/deploy/candidates.py <ENV>
```

The script prints `<name>: <sha> <version> <pushed|tagged|unpushed>` for `local` (the tip of the local `main`), `dev`
(the tip of `origin/main`), `release` (the newest commit on `main` or `origin/main` whose `__version__` is a plain
`X.Y.Z`) and `space` (the Space's `main` now), then `running: <stage> <sha>`, what the Space actually runs. `pushed`
means the commit is on `origin/main`. `tagged` means it is on GitHub through a tag but not on `main` there:
`/release` pushes the release tag, and its commits reach `main` with the next `/push`.

Use AskUserQuestion with what the Space runs in the question text, e.g. "The Space runs 0.3.1 (d6bb48b, RUNNING).
Which version to deploy?", and one option per candidate, with the exact version and short sha as the label and
whether it is pushed in the description:

- `0.4.0.dev0 (e5a1cbb)` (local): the latest local commit on `main`, not pushed to GitHub
- `0.4.0.dev0 (abc1234)` (dev): the latest commit on GitHub's `main`
- `0.3.1 (d6bb48b)` (release): the latest release (if `tagged`: on GitHub as tag `v0.3.1`, not on its `main` yet)

Don't mark a default. Drop a candidate that is `none`, and offer a commit once when several candidates are the same
commit (e.g. `local` and `dev` when `main` is pushed). If the user picks "Other", accept any commit. Then work out
how to push it:

```bash
uv run python .claude/skills/deploy/plan_push.py <rev> <ENV>
```

It prints the full sha of the commit (`TARGET` from here on; `Not a commit` means ask again), the Space's `main`
(`PREVIOUS` from here on, used in step 4), what the Space runs, and a `push:` line:

- `none`: the Space already has `TARGET` and runs it. Nothing needs deploying: skip to step 5 to smoke-test and
  report.
- `push`: a plain push. Continue with step 3.
- `rollback`: `TARGET` is a rollback or a different branch of history (e.g. the release when the Space runs a later
  dev commit), so the push is forced; the script lists the commits the Space would lose. On staging, continue with
  step 3 without asking. On production, show the user those commits and ask them to confirm with AskUserQuestion;
  continue only after they confirm.
- `foreign`: the Space has commits that exist nowhere else (e.g. edits made on huggingface.co). Stop and report the
  commits the script lists; never overwrite them.

## 3. Push to the Space

Run the `command:` line that `plan_push.py` printed, as it is. For a rollback it forces the push only over the commit
the script checked (`--force-with-lease`).

Git authenticates to huggingface.co with the HF token stored in its credential helper. If the push fails with an
authentication error (e.g. `could not read Username for 'https://huggingface.co'`), stop and tell the user to
store a token with write access to the Space (e.g. `hf auth login --add-to-git-credential`). If the push is
rejected for any other reason, stop and report.

## 4. Wait for the Space to build and start

Pushing triggers a Docker rebuild. Wait until the Space runs the pushed commit, with a Bash timeout of at least
960000 ms. The script polls the runtime API every 20 s for up to 15 min and prints each stage:

```bash
uv run python .claude/skills/deploy/wait_space.py <TARGET> <ENV>
```

It exits 0 when the Space is `RUNNING` on that sha, 1 on an error stage and 2 on timeout.

- `BUILDING`, `RUNNING_BUILDING`, `APP_STARTING` (or the old sha still `RUNNING`): keep waiting.
- `RUNNING` with `sha` equal to `TARGET`: continue.
- `BUILD_ERROR`, `RUNTIME_ERROR` or `CONFIG_ERROR`: stop. Report the stage and point the user to the **Logs** tab
  of the Space page (build and container logs need a token to read through the API). Reproduce a build failure
  locally with `docker build .` if useful.
- Still not running the new sha after ~15 min: stop and report the last stage seen.

### Check that the image was really rebuilt

HF's Docker layer cache can reuse the old image: every step of the build log is `CACHED`, even `COPY src`, yet the
runtime reports the new sha as `RUNNING` while the old code serves. Check the build log:

```bash
uv run python .claude/skills/deploy/check_build.py <TARGET> <PREVIOUS> <ENV>
```

It exits 0 for a fresh build of `TARGET`. It exits 1 when the latest build is for another commit, or when a `COPY`
step was `CACHED` although the files it copies changed between `PREVIOUS` and `TARGET`, and prints why. It exits 2
when it can't read the log (it needs the stored HF token). Skip this check when step 2 found nothing to deploy.

On exit 1, ask the user with AskUserQuestion whether to run a factory rebuild (same commit, no layer cache; the
site is down for about a minute). Only after they confirm:

```bash
uv run python -c "from huggingface_hub import HfApi; HfApi().restart_space('<SPACE>', factory_reboot=True)"
uv run python .claude/skills/deploy/wait_space.py --restarted <TARGET> <ENV>
uv run python .claude/skills/deploy/check_build.py <TARGET> <PREVIOUS> <ENV>
```

`--restarted` waits for the Space to leave `RUNNING` first, since the old container already reports `TARGET`. If
the check still fails, or the user declines, stop and report. On exit 2, report it and rely on the version checks
in step 5.

## 5. Smoke-test the live site

```bash
uv run python .claude/skills/deploy/smoke.py <TARGET> <ENV> --ask "Maintained forks of Review Heatmap"
```

The script prints one `PASS` or `FAIL` line per check and exits 1 if any check fails:

- `/healthz` (and on production the custom domain) must report the version of `TARGET`. Development versions don't
  change on every commit, so the runtime sha and the build check (step 4) prove the new commit is live, not the
  version.
- The home page must contain "Highest rated", the search must return at least one card, and the add-on and top
  pages must return 200. These pages read from the in-process MCP server, which loads the dataset from the HF Hub on
  start, so the first page can take seconds.
- The About page must show the `anki-addons-mcp` version locked in `uv.lock` at `TARGET` (the one the tests ran
  against). Another version means the Space serves an old image (see "Check that the image was really rebuilt" in
  step 4).
- The run log must say "MCP server: in-process". A URL there means the Space variable `ANKI_CATALOG_MCP_URL` is set:
  warn the user, since the HF proxy answers requests from the catalog Space to the MCP Space with HTTP 429 in bursts
  (README-DEV, "MCP server").
- `--ask` asks the AI search one question as the admin, which skips Turnstile and the rate limit; the daily budget
  still applies. It costs a few cents of Claude credits, which the user allows for smoke testing. The answer must
  end with `answer`, `addons`, `done` and show at least one card; the detail gives the number of cards and how many
  of them have a summary. A Turnstile request means the local admin password is not the Space's
  `ANKI_CATALOG_ADMIN_TOKEN`; an error shows its message (budget spent, catalog unavailable). Report it; don't retry.
  Ask one question per deploy: answers are cached per question for the life of the container, so asking again
  tests nothing. If the deployed commit changed AI search, pick a question that exercises the change instead.
- If the deployed commit changed a page, add `--page <path>=<text>` (repeatable) with a text the change shows; it
  must return 200 and contain the text.

If a check fails, report the output and point the user to the **Logs** tab of the Space page.

## Done

Report the target, the deployed version and commit SHA (and the previous ones the Space ran), the runtime stage, the
build check (and any factory rebuild) and the smoke-test results, or the first step that failed and why.
