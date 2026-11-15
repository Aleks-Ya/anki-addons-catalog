"""Print what changed in anki-addons-mcp between two releases: the evidence /update-mcp reviews.

Usage: uv run python .claude/skills/update-mcp/changes.py <base> <target>   (versions X.Y.Z, e.g. 0.11.0 0.12.0)
Run from the repository root. Reads GitHub's comparison of the tags v<base>...v<target> and prints sections: the
commits (subject and body) without the version bumps; the dataset tag the server pins, before and after; the patches
of the MCP surface the AI uses (tools, server instructions, result models, filters, settings), of every other MCP
module the app imports, of the user docs and of the MCP's test fixture (the real shapes of the data); and one stat line
for every other changed file. Exits 0, or 1 when GitHub can't compare the tags.
"""
import sys
from typing import Any

from mcp_repo import compare, file_at, hf_revision, is_routine, mcp_imports, module_files

PKG = "src/anki_addons_mcp/"
SURFACE = [f"{PKG}interface/mcp/tools.py", f"{PKG}interface/mcp/server.py", f"{PKG}domain/models.py",
           f"{PKG}domain/query.py", f"{PKG}config.py"]
DOCS = ["README.md", "docs/reference.md", "docs/configuration.md", "docs/dataset-notes.md"]
FIXTURES = ["tests/fixtures/dataset.py"]


def commit_messages(comparison: dict[str, Any]) -> list[str]:
    """The full messages of the compared commits, oldest first, without the routine ones."""
    messages = [c["commit"]["message"].strip() for c in comparison["commits"]]
    return [m for m in messages if not is_routine(m.splitlines()[0])]


def sections(files: list[dict[str, Any]], imported: list[str]) -> list[tuple[str, list[dict[str, Any]]]]:
    """The changed files grouped into the printed sections; a file goes into the first section that names it."""
    groups = [("MCP surface the AI uses", SURFACE), ("Other MCP modules the app imports", imported),
              ("User docs", DOCS), ("MCP test fixture (real data shapes)", FIXTURES)]
    taken: set[str] = set()
    result = []
    for title, paths in groups:
        chosen = [f for f in files if f["filename"] in paths and f["filename"] not in taken]
        taken.update(f["filename"] for f in chosen)
        result.append((title, chosen))
    result.append(("Other changed files (no patch shown)", [f for f in files if f["filename"] not in taken]))
    return result


def describe(file: dict[str, Any]) -> str:
    return f"{file['filename']} ({file['status']}, +{file['additions']} -{file['deletions']})"


def main(base: str, target: str) -> int:
    comparison = compare(f"v{base}", f"v{target}")
    print(f"== Commits v{base}...v{target} ({comparison['total_commits']}, version bumps left out) ==")
    for message in commit_messages(comparison):
        print(f"\n{message}")
    before, after = (hf_revision(file_at(f"{PKG}config.py", f"v{v}")) for v in (base, target))
    print(f"\n== Dataset tag (hf_revision) ==\n{before} -> {after}" + (" (unchanged)" if before == after else ""))
    imported = [path for module in mcp_imports() for path in module_files(module)]
    for title, files in sections(comparison["files"], imported):
        print(f"\n== {title} ==")
        for file in files:
            if title.startswith("Other changed"):
                print(describe(file))
            else:
                print(f"\n--- {describe(file)}")
                print(file.get("patch") or "(no patch from GitHub: too large or binary; read the file at both tags)")
        if not files:
            print("(none)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
