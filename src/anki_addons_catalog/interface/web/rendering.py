from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict


def _resolve(url: str, base: str | None) -> str:
    """Resolves a relative README link against the repository, as GitHub does (a leading "/" is the repository root)."""
    if not base or not url or url.startswith(("#", "//")) or urlsplit(url).scheme:
        return url
    return urljoin(base, url.lstrip("/"))


def _link_open(self: RendererHTML, tokens: list[Token], idx: int, options: OptionsDict, env: EnvType) -> str:
    token = tokens[idx]
    href = _resolve(str(token.attrGet("href") or ""), env.get("link_base"))
    token.attrSet("href", href)
    if href.startswith(("http://", "https://")):
        token.attrSet("rel", "nofollow noopener noreferrer")
        token.attrSet("target", "_blank")
    return self.renderToken(tokens, idx, options, env)


def _image(self: RendererHTML, tokens: list[Token], idx: int, options: OptionsDict, env: EnvType) -> str:
    token = tokens[idx]
    token.attrSet("src", _resolve(str(token.attrGet("src") or ""), env.get("image_base")))
    return self.image(tokens, idx, options, env)


def _markdown() -> MarkdownIt:
    """CommonMark + tables with raw HTML disabled: READMEs and AI answers are untrusted input."""
    md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").enable("strikethrough")
    md.add_render_rule("link_open", _link_open)
    md.add_render_rule("image", _image)
    return md


_MD = _markdown()


def render_markdown(text: str | None) -> str:
    return _MD.render(text) if text else ""


def render_readme(text: str | None, github_user: str | None, github_repo: str | None) -> str:
    """Renders a GitHub README; relative links and images point into the repository's default branch."""
    if not text:
        return ""
    if not github_user or not github_repo:
        return str(_MD.render(text))
    repo = f"https://github.com/{github_user}/{github_repo}"
    return str(_MD.render(text, {"link_base": f"{repo}/blob/HEAD/", "image_base": f"{repo}/raw/HEAD/"}))


def compact_number(value: Any) -> str:
    if not isinstance(value, int | float):
        return "–"
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return str(value)


def human_date(value: str | None) -> str:
    """"2026-10-01" -> "1 Oct 2026"; anything else is returned as is."""
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value or "")
    return f"{day.day} {day:%b %Y}"
