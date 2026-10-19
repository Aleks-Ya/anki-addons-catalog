---
name: release
description: Bump the version for a release — show the current version, offer the exact major, minor and patch versions to choose from, bump to the chosen one with bump-my-version and commit. Does not tag, push or deploy. Use when the user says "release", "/release", or asks to bump the version.
allowed-tools: Bash(git *) Bash(uv run bump-my-version *) Bash(python3 .claude/skills/release/versions.py)
disable-model-invocation: true
---

# release

Bump the version (README-DEV.md → "Release a new version") to a major, minor or patch release the user picks, and
commit it. The version lives in `src/anki_addons_catalog/__init__.py` (`__version__`) and in
`.bumpversion.toml` (`current_version`); bump-my-version updates both and commits (`commit = true`,
`tag = false`). This skill does not tag, push or deploy: run `/push` and `/deploy` afterwards. Work through the
steps in order; stop and report if a step can't be completed.

## 1. Preconditions

```bash
git rev-parse --abbrev-ref HEAD
git status --porcelain
```

If not on `main`, or there is **any** `git status` output, stop and report: bump-my-version refuses a dirty tree
(`allow_dirty = false`). Do not commit on the user's behalf.

## 2. Work out the three candidate versions

```bash
python3 .claude/skills/release/versions.py
```

It prints the current version, the last release tag and the major, minor and patch candidates. A `.dev0` version
is not released yet, so the candidates count from the last release tag; a release version counts from itself
(`1.2.2` gives `2.0.0`, `1.3.0` and `1.2.3`).

## 3. Ask which version to release

Use AskUserQuestion with the current version in the question text, e.g. "Current version is 0.3.0.dev0 (last
release v0.2.0). Which version to release?", and three options with the exact versions as labels:

- `1.0.0` (major): breaking changes
- `0.3.0` (minor): new features
- `0.2.1` (patch): fixes only

Don't mark a default. If the user picks "Other", accept only a plain `X.Y.Z` that is higher than the last
release; otherwise ask again.

## 4. Bump and commit

Dry-run first, then bump for real:

```bash
uv run bump-my-version bump --new-version <version> --dry-run -v
uv run bump-my-version bump --new-version <version>
```

The dry run must show changes to `src/anki_addons_catalog/__init__.py` and `.bumpversion.toml` and the commit
message `Bump version: <current> → <version>`. A warning that the current version doesn't match the last
tagged version is expected after a `.dev0` version. If anything else looks wrong, stop and report.

Then check the result:

```bash
git log -1 --stat --format='%h %s'
git status --porcelain
grep -n __version__ src/anki_addons_catalog/__init__.py
```

The commit must touch only those two files, and the tree must be clean.

## Done

Report the old and new versions and the commit SHA. End with: "Push with `/push`, then deploy with `/deploy`."
