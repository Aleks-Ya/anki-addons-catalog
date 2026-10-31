"""Print the GitHub Release notes for a tag: one line per commit since the previous release tag.

Merge and "Bump version" commits are left out. The first tag has no previous tag, so it lists all history up to it.
Run from the repository root: notes.py v1.2.3
"""
import subprocess
import sys


def previous_tag(tag: str) -> str:
    result = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", f"{tag}^"],
                            check=False, capture_output=True, text=True)  # no previous tag is fine
    return result.stdout.strip()


def notes(tag: str) -> list[str]:
    previous = previous_tag(tag)
    revisions = f"{previous}..{tag}" if previous else tag
    subjects = subprocess.run(["git", "log", "--no-merges", "--format=%s", revisions],
                              check=True, capture_output=True, text=True).stdout.splitlines()
    return [f"- {subject}" for subject in subjects if not subject.startswith("Bump version")]


if __name__ == "__main__":
    print("\n".join(notes(sys.argv[1])))
