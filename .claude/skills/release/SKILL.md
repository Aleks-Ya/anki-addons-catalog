---
name: release
description: Bump the version for a release — show the current version, offer the exact major, minor and patch versions to choose from, bump to the chosen one with bump-my-version, commit and tag it, switch to the next development version (`.dev0`) in a second commit, then push the tag and publish a GitHub Release. Requires `main` to be pushed already. Does not push `main` or deploy. Use when the user says "release", "/release", or asks to bump the version.
allowed-tools: Bash(git *) Bash(uv run bump-my-version *) Bash(gh auth status) Bash(gh release *) Bash(python3 .claude/skills/release/versions.py) Bash(python3 .claude/skills/release/notes.py *)
disable-model-invocation: true
---

# release

Bump the version to a major, minor or patch release the user picks, commit and tag it, then switch to the next
development version and commit that too. The version lives in `src/anki_addons_catalog/__init__.py` (`__version__`)
and in `.bumpversion.toml` (`current_version`); bump-my-version updates both and commits (`commit = true`). Only the
release commit gets a tag, through `--tag`: the config has `tag = false` so that the development bump stays untagged.
This skill pushes only the release tag and publishes a GitHub Release for it. It does not push `main` or deploy: run
`/push` and `/deploy` afterwards. Work through the steps in order; stop and report if a step can't be completed.

## 1. Preconditions

```bash
git rev-parse --abbrev-ref HEAD
git status --porcelain
git fetch -q origin
git rev-parse main origin/main
gh auth status
```

Stop and report, before any commit is made, if any of these fails:

- The current branch is `main`.
- `git status` prints nothing: bump-my-version refuses a dirty tree (`allow_dirty = false`). Do not commit on the
  user's behalf.
- `main` is pushed: the two `git rev-parse` lines are equal. If not, list the commits that differ
  (`git log --oneline origin/main..main` and `git log --oneline main..origin/main`) and tell the user to run `/push`
  first. The released code must have been through `/push`, with its checks and CI, because the Release goes public.
- `gh auth status` succeeds: step 6 needs it.

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
uv run bump-my-version bump --new-version <version> --tag --dry-run -v
uv run bump-my-version bump --new-version <version> --tag
```

The dry run must show changes to `src/anki_addons_catalog/__init__.py` and `.bumpversion.toml`, the commit
message `Bump version: <current> → <version>` and the tag `v<version>`. A warning that the current version doesn't
match the last tagged version is expected after a `.dev0` version. If anything else looks wrong, stop and report.

Then check the result:

```bash
git log -1 --stat --format='%h %s'
git tag --points-at HEAD
git status --porcelain
grep -n __version__ src/anki_addons_catalog/__init__.py
```

The commit must touch only those two files, `git tag` must print `v<version>`, and the tree must be clean.

## 5. Switch to the next development version

Right after the release commit, bump to the next minor `.dev0` version (`0.3.1` gives `0.4.0.dev0`), without a tag.
Dry-run first, then bump for real:

```bash
uv run bump-my-version bump minor --dry-run -v
uv run bump-my-version bump minor
```

The dry run must show the same two files changing to `<next minor>.dev0` and the commit message
`Bump version: <version> → <next minor>.dev0`. If anything else looks wrong, stop and report.

Then check the result:

```bash
git log -2 --stat --format='%h %s'
git status --porcelain
grep -n __version__ src/anki_addons_catalog/__init__.py
```

The release commit and the dev commit must each touch only those two files, `__version__` must end in `.dev0`,
and the tree must be clean.

## 6. Publish the GitHub Release

Push only the release tag, then publish the Release with one note line per commit since the previous tag:

```bash
git push origin v<version>
python3 .claude/skills/release/notes.py v<version> \
  | gh release create v<version> --verify-tag --title v<version> --notes-file -
```

`--verify-tag` stops `gh` from creating a tag on the wrong commit if the tag is not on GitHub. The two bump commits
stay local until `/push`.

## Done

Report the old version, the release version with its commit SHA, tag and GitHub Release URL, and the new development
version and its commit SHA. End with: "Push with `/push`, then deploy with `/deploy`."
