---
name: release
description: Bump the version for a release — show the current version, offer the exact major, minor and patch versions to choose from, bump to the chosen one with bump-my-version, commit and tag it, switch to the next development version (`.dev0`) in a second commit, then push the tag with the release commit as GitHub's `main` and publish a GitHub Release. Requires `main` to be pushed already. Does not push the development commit or deploy. Use when the user says "release", "/release", or asks to bump the version.
allowed-tools: Bash(git *) Bash(uv run bump-my-version *) Bash(gh release *) Bash(python3 .claude/skills/release/versions.py) Bash(python3 .claude/skills/release/versions.py *) Bash(python3 .claude/skills/release/verify.py *) Bash(python3 .claude/skills/release/notes.py *)
disable-model-invocation: true
---

# release

Bump the version to a major, minor or patch release the user picks, commit and tag it, then switch to the next
development version and commit that too. The version lives in `src/anki_addons_catalog/__init__.py` (`__version__`)
and in `.bumpversion.toml` (`current_version`); bump-my-version updates both and commits (`commit = true`). Only the
release commit gets a tag, through `--tag`: the config has `tag = false` so that the development bump stays untagged.
This skill pushes the release tag and moves GitHub's `main` to the release commit, so `/deploy` sees the release as
pushed, and publishes a GitHub Release for it. It does not push the development commit or deploy: run `/push` and
`/deploy` afterwards. Work through the steps in order; stop and report if a step can't be completed.

## 1. Preconditions

```bash
python3 .claude/skills/release/verify.py pre
```

The script fetches `origin` and checks that the current branch is `main`, the tree is clean (bump-my-version refuses
a dirty tree: `allow_dirty = false`), `main` equals `origin/main`, and `gh` is logged in (step 6 needs it). If any
line is `FAIL`, stop and report it before any commit is made. Do not commit on the user's behalf. If `main` is not
pushed, the script lists the commits that differ: tell the user to run `/push` first. The released code must have
been through `/push`, with its checks and CI, because the Release goes public.

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

Don't mark a default. If the user picks "Other", check their version with
`python3 .claude/skills/release/versions.py <version>`: accept it only when it prints `ok` (a plain `X.Y.Z` higher
than the last release); otherwise tell them why and ask again.

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
python3 .claude/skills/release/verify.py release <version>
```

It checks that `HEAD` is the release commit with the tag `v<version>`, that it touches only those two files, that
`__version__` is `<version>` and that the tree is clean. If any line is `FAIL`, stop and report.

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
python3 .claude/skills/release/verify.py dev <version>
```

It checks that the untagged dev commit sits on top of the tagged release commit, that each touches only those two
files, that `__version__` is `<next minor>.dev0` and that the tree is clean. If any line is `FAIL`, stop and report.

## 6. Publish the GitHub Release

Push the release tag and move GitHub's `main` to the release commit (the commit the tag points to, not the
development commit on top of it), then publish the Release with one note line per commit since the previous tag:

```bash
git push --atomic origin v<version> v<version>^{commit}:refs/heads/main
python3 .claude/skills/release/notes.py v<version> \
  | gh release create v<version> --verify-tag --title v<version> --notes-file -
```

`--atomic` pushes both refs or neither. Step 1 checked that `origin/main` equals `main`, so the release commit sits
directly on top of `origin/main` and the push adds only that commit. If the push is rejected (e.g. someone pushed to
`main` meanwhile), stop and report; never force it. The push starts the Unit-tests workflow on the release commit;
don't wait for it, since the commit changes only the version. `--verify-tag` stops `gh` from creating a tag on the
wrong commit if the tag is not on GitHub. The development commit stays local until `/push`.

## Done

Report the old version, the release version with its commit SHA, tag and GitHub Release URL, and the new development
version and its commit SHA. End with: "Push with `/push`, then deploy with `/deploy`."
