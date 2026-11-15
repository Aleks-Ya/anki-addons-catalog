---
name: update-mcp
description: Upgrade the pinned anki-addons-mcp server to a newer release and use what it adds — list the MCP releases after the pinned version and recommend one, review its commits and diff on GitHub (tools, result fields, filters, docs, dataset tag), cross-check what the app relies on, write what the MCP itself must change as a ready-to-paste AI prompt, propose the app changes and get the user's approval in plan mode, then implement, check locally with the real dataset and a few real AI questions, and commit. Use when the user says "update mcp", "/update-mcp", or asks to upgrade the MCP server.
allowed-tools: Bash(git *) Bash(gh api *) Bash(uv *)
disable-model-invocation: true
---

# update-mcp

The app runs [anki-addons-mcp](https://github.com/Aleks-Ya/anki-addons-mcp) in-process, pinned to an exact version
(`anki-addons-mcp==X.Y.Z` in `pyproject.toml`, the same in `uv.lock`). A new MCP release can add tools, filters and
result fields, rename or drop fields, and move to a new dataset tag, so the app is upgraded on purpose: this skill
moves the pin to a newer release and adapts the app to it.

The skill has **two outputs**, and both are reported explicitly:

1. **App changes**: proposed, approved by the user, implemented, checked and committed in this repo.
2. **MCP change requests**: what must change in the MCP server itself, which this skill must not do (CLAUDE.md). They
   go to the user as a ready-to-paste AI prompt for a session in the MCP repo. When there are none, say "None".

The MCP repo is **read-only**: the scripts read it through GitHub (`gh api`). Never change `../anki-addons-mcp` (not
even `git fetch` or a checkout); reading its files with `git -C ../anki-addons-mcp show <tag>:<path>` is fine.

**No file of this repo is edited before the user approves the proposal in step 6.**

Work through the steps in order; stop and report if a step can't be completed.

Scripts (in `.claude/skills/update-mcp/`, run from the repo root with `uv run python <script>`; `<s>` below stands for
that directory). Each prints its result and stops the agent through its exit code; the usage is in each file's
docstring:

| Script | Answers | Exit |
|---|---|---|
| `ready.py` | Branch `main`, clean tree, an exact pin in `pyproject.toml`, the same version in `uv.lock` | 0 ok, 1 not |
| `releases.py [--target X.Y.Z]` | The pinned version, newer releases with dates, PyPI status and commits, the recommended one, unreleased MCP commits; with `--target` whether that version can be the upgrade | 0 found/ok, 1 invalid, 2 up to date |
| `changes.py <base> <target>` | The commits, the dataset tag before and after, and the patches of the MCP surface, the modules the app imports, the docs and the MCP's fixture | 0 |
| `impact.py <base> <target>` | `FAIL` for what the app relies on and the target breaks (tools, arguments, imports, result fields the app names), `NEW` tools, parameters and fields, `INFO` the rest | 0 nothing breaks, 1 a FAIL |
| `pin.py <target>` | Moves the pin, the lock and the environment; lists the packages that moved | 0 ok, 1 not |
| `local_check.py <target> [--page P[=T]]... [--ask Q]...` | The app on the real dataset: startup, pages, up to 3 real AI questions and their cost | 0 ok, 1 not |
| `verify_upgrade.py <target>` | The upgrade commit: subject, pin and lock at `HEAD`, clean tree | 0 ok, 1 not |

## 1. Preconditions

```bash
uv run python <s>/ready.py
```

Exit 1: stop and report the `FAIL` lines. Don't commit or stash anything on the user's behalf.

## 2. Pick the version

```bash
uv run python <s>/releases.py
```

- Exit 2: report "up to date" with the pinned version, plus the unreleased MCP commits if it lists any (they need an
  MCP release first: `/release` in the MCP repo), and stop.
- If the user gave a version (`/update-mcp 0.12.0`), check it with `releases.py --target <version>`: exit 1 → tell the
  user why and stop.
- Otherwise use AskUserQuestion, e.g. "The app is pinned to anki-addons-mcp 0.11.0. Which version to upgrade to?",
  with one option per release on PyPI, newest first, the recommended one marked "(Recommended)", each with its date
  and its main commit subjects in the description. A release `NOT on PyPI` can't be installed: leave it out.

Remember `<base>` (the pinned version) and `<target>` (the chosen one).

## 3. Collect the changes

Run both, in one message (they are independent):

```bash
uv run python <s>/changes.py <base> <target>
uv run python <s>/impact.py <base> <target>
```

`impact.py` exits 1 when it finds a `FAIL`: that is evidence for step 4, not a reason to stop. Where a patch is not
enough (a long file, a patch GitHub left out), read the whole file at the tag:
`git -C ../anki-addons-mcp show v<target>:<path>` when the tag is local, else
`gh api -H 'Accept: application/vnd.github.raw' 'repos/Aleks-Ya/anki-addons-mcp/contents/<path>?ref=v<target>'`.

## 4. Analyse the impact on the app

List every change from step 3 and classify it:

| Kind | Examples | App action |
|---|---|---|
| Breaking | every `impact.py` FAIL; a field whose meaning or source changed under the same name | must fix |
| New capability | `NEW` tools, parameters and fields; new data from the dataset tag | candidate: the user decides where |
| Changed meaning | tool descriptions, server instructions, verdict rules, vocabulary | align the prompt, labels, fixtures |
| Dataset tag | `hf_revision` moves | new snapshots and data; check the fields pages show |
| Internal | refactoring, MCP tests, MCP dependencies | none beyond the pin |

Map each change to the app. The touch points, from past upgrades (`git log --grep "anki-addons-mcp"`):

- `src/anki_addons_catalog/config.py`: `ai_tools`, the tools the AI may call (a new tool reaches the AI only here)
- `application/ask.py`: `SYSTEM_PROMPT`, `FILTERED_TOOLS`, `THIN_CARD_TOOLS`, `with_filters`, `extract_cards`
- `domain/models.py`: `AddonCard` and `from_details` (cards from `get_addon` records), `SearchFilters` and `tool_args`
- `application/catalog.py` (direct tool calls, `STAT_GROUPS`), `interface/web/app.py`
- templates `addon.html`, `_cards.html`, `_filters.html`, `stats.html`
- `tests/fixtures.py` (built with the MCP's own models and in-memory repository), `tests/interface/test_web.py`,
  `tests/application/test_ask.py`, `tests/application/test_catalog_service.py`
- README.md where it lists what the site shows

Rules:

- The app does not pass the MCP server's instructions to Claude: advice added there goes into `SYSTEM_PROMPT` if the
  AI should follow it.
- Cards come from two places: search results (the MCP builds them) and `AddonCard.from_details` (the app builds them
  from `get_addon`). Keep both the same when a card field changes.
- UI text is simple English for international users: no idioms or phrasal verbs. The proposal gives the exact
  wording of every new label and prompt sentence.
- `ai_summary`, `ai_tags` and other AI fields may be wrong: show them as AI-generated, as the app does now.

## 5. MCP change requests

This step always runs. Collect a request for everything the app needs that belongs in the MCP server: a field or
filter the app would otherwise compute itself, a description the changes contradict, a change that looks like a bug.
Don't work around it in the app (CLAUDE.md).

When there is at least one, write `<scratchpad>/mcp-change-requests.md`, a prompt for a Claude Code session in
`/home/aleks/pr/home/anki-addons-mcp`, stated as the wanted result: no file names, function names, code or test
instructions (that session decides them):

```markdown
# Requests from anki-addons-catalog after the upgrade to anki-addons-mcp <target>

Context: anki-addons-catalog (the web app) runs this server in-process, pinned to a release. While moving to
<target> it found the problems below. Please fix them and publish a new release.

## 1. <short title> (blocking | not blocking)
Problem: ...
Evidence: <the tool call or data that shows it>
Wanted result: ...
Why the app needs it: ...
```

Print the prompt in full in a fenced block and give the file path. For each **blocking** request, ask with
AskUserQuestion: stop and wait for an MCP release (rerun `/update-mcp` after it), or upgrade without the affected
part (the proposal then names what is left out). Non-blocking requests don't stop the run.

## 6. Propose and get approval

Enter plan mode with `EnterPlanMode` and write the proposal with these sections:

1. **Context**: `<base>` → `<target>`, the release dates, the dataset tag before and after.
2. **MCP changes found**: a table of every change from step 4: change, kind, commit.
3. **App changes**: per change, what the app does, the files, and the exact wording of new UI text and prompt text.
   The pin is always one of them.
4. **Left unused**: changes deliberately not used, and why.
5. **MCP change requests**: the numbered list from step 5 with the prompt path, or "None".
6. **Verification**: step 8, with the pages and the questions you will check.
7. **Commit**: the message of step 9.

Ask the user's rulings with AskUserQuestion before submitting, wherever the answer changes the proposal, e.g. use
the new field X, and where (addon page, cards, filters, stats, the AI prompt only); recommend an option.

Submit with `ExitPlanMode`. If the user rejects it or comments, revise and submit again. Only an approved proposal is
implemented.

## 7. Implement

```bash
uv run python <s>/pin.py <target>
```

Exit 1: stop and report. Otherwise note the `moved:` packages for the report, then make the approved changes,
including the fixtures and tests (`tests/fixtures.py` must build the target's models the way the MCP's own fixture
does).

## 8. Verify

```bash
uv run ruff check src tests .claude/skills
uv run mypy
uv run pytest
```

Fix failures and rerun until green. Then check the app on the real dataset. Run it in the background (it downloads
the target's dataset, up to 10 minutes):

```bash
uv run python <s>/local_check.py <target> --log <scratchpad>/app.log \
  --page "/addon/<id>=<new text>" --ask "<question that uses the change>"
```

- Add a `--page` for every page the change touched, with a text the change shows.
- Add an `--ask` only when the change affects AI search (prompt, tools, `ai_tools`, tool results), at most 3, each one
  exercising the change. Each costs a few cents of Claude credits, which CLAUDE.md allows; ask the user before more.
  Answers are cached per question for the life of the app, so asking the same question twice tests nothing.
- Exit 1: read the `FAIL` lines and the log, fix, and rerun the checks. A fix outside the approved proposal needs the
  user's OK first.

## 9. Commit

Commit everything as one commit (the proposal announced it, so the approval covers it). The subject is
`Upgrade to anki-addons-mcp <target>`, plus ` and <what the app now does>` when users see a change; the body says
what changed in the MCP and what the app does about it, in the style of the earlier upgrades
(`git log --grep "Upgrade to anki-addons-mcp" -3`). Never push. Then:

```bash
uv run python <s>/verify_upgrade.py <target>
```

Exit 1: fix and check again (e.g. a forgotten file: amend this commit, which was not pushed).

## Done

Report in two explicitly separate parts:

- **App**: `<base>` → `<target>`, the commit SHA, the changes made, the changes left unused, the `moved:` packages,
  the check results, and the AI questions with the total cost.
- **MCP change requests**: the numbered list with blocking or not blocking and the prompt path, or "None".

End with: "Push with `/push`, then deploy with `/deploy`." For `/deploy`, suggest an `--ask` question that uses the
change.
