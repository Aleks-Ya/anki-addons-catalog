"""The two Spaces /deploy can deploy to, and the git and HF helpers its scripts share.

Every script takes the target name (`production` or `staging`), so a deploy to staging can't check production by
mistake. Run the scripts with `uv run python` from the repository root: the runtime needs the stored HF token.
"""
import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass

VERSION_FILE = "src/anki_addons_catalog/__init__.py"


@dataclass(frozen=True)
class Target:
    remote: str
    space: str
    site: str
    domain: str | None  # the custom domain, checked as well as the site
    private: bool  # requests to the site need the HF token
    admin_token_var: str  # the admin password in the local .env


TARGETS = {
    "production": Target(remote="space", space="Ya-Alex/anki-addons-catalog",
                         site="https://ya-alex-anki-addons-catalog.hf.space",
                         domain="https://www.anki-addons-catalog.com", private=False,
                         admin_token_var="ANKI_CATALOG_ADMIN_TOKEN"),
    "staging": Target(remote="space-staging", space="Ya-Alex/anki-addons-catalog-staging",
                      site="https://ya-alex-anki-addons-catalog-staging.hf.space", domain=None, private=True,
                      admin_token_var="ANKI_CATALOG_STAGING_ADMIN_TOKEN"),
}


def get_target(name: str) -> Target:
    if name not in TARGETS:
        raise SystemExit(f"Unknown target {name!r}: use {' or '.join(TARGETS)}")
    return TARGETS[name]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def ref_sha(ref: str) -> str | None:
    result = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], check=False,
                            capture_output=True, text=True)
    return result.stdout.strip() or None


def is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant], check=False).returncode == 0


def version_at(sha: str) -> str:
    match = re.search(r'__version__ = "([^"]+)"', git("show", f"{sha}:{VERSION_FILE}"))
    return match.group(1) if match else "?"


def hf_token() -> str | None:
    from huggingface_hub import get_token  # only in the uv environment
    return get_token()


def runtime(space: str) -> tuple[str, str | None]:
    """The stage and the sha the Space runs, from the runtime API."""
    token = hf_token()
    request = urllib.request.Request(f"https://huggingface.co/api/spaces/{space}/runtime",
                                     headers={"Authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    return data["stage"], data.get("sha")
