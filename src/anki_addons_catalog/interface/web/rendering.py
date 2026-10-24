from datetime import date
from functools import partial
from typing import Any
from urllib.parse import urljoin, urlsplit

import nh3
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
    elif env.get("new_tab"):
        token.attrSet("target", "_blank")
    return self.renderToken(tokens, idx, options, env)


def _image(self: RendererHTML, tokens: list[Token], idx: int, options: OptionsDict, env: EnvType) -> str:
    token = tokens[idx]
    token.attrSet("src", _resolve(str(token.attrGet("src") or ""), env.get("image_base")))
    return self.image(tokens, idx, options, env)


def _markdown(html: bool) -> MarkdownIt:
    """CommonMark + tables; raw HTML only where the output is sanitized afterwards."""
    md = MarkdownIt("commonmark", {"html": html, "linkify": False}).enable("table").enable("strikethrough")
    md.add_render_rule("link_open", _link_open)
    md.add_render_rule("image", _image)
    return md


_MD = _markdown(html=False)  # AI answers: raw HTML is escaped
_README_MD = _markdown(html=True)  # READMEs: raw HTML (as GitHub renders it) passes through _sanitize

_README_TAGS = {
    "p", "div", "span", "a", "img", "picture", "source", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
    "blockquote", "pre", "code", "em", "strong", "del", "s", "b", "i", "u", "br", "hr", "table", "thead", "tbody",
    "tr", "th", "td", "details", "summary", "sub", "sup", "kbd", "dl", "dt", "dd",
}
_README_ATTRIBUTES = {
    "*": {"align", "id", "name"},
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "source": {"srcset", "media", "type"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "ol": {"start"},
    "details": {"open"},
    "code": {"class"},
}


def _resolve_attribute(link_base: str | None, image_base: str | None, tag: str, attribute: str, value: str) -> str:
    """Resolves relative URLs in README raw HTML, as the markdown link and image rules do."""
    if tag == "a" and attribute == "href":
        return _resolve(value, link_base)
    if attribute in ("src", "srcset") and tag in ("img", "source"):
        return _resolve(value, image_base)
    return value


def _sanitize(html: str, link_base: str | None, image_base: str | None,
              set_tag_attribute_values: dict[str, dict[str, str]] | None = None) -> str:
    return str(nh3.clean(
        html, tags=_README_TAGS, attributes=_README_ATTRIBUTES,
        tag_attribute_values={"a": {"target": {"_blank"}}}, set_tag_attribute_values=set_tag_attribute_values,
        link_rel="nofollow noopener noreferrer", url_schemes={"http", "https", "mailto"},
        attribute_filter=partial(_resolve_attribute, link_base, image_base)))


def render_markdown(text: str | None, new_tab: bool = False) -> str:
    """Renders an AI answer; with new_tab, catalog links open in a new tab too (external ones always do)."""
    return _MD.render(text, {"new_tab": new_tab}) if text else ""


def render_readme(text: str | None, github_user: str | None, github_repo: str | None) -> str:
    """Renders a GitHub README; relative links and images point into the repository's default branch."""
    if not text:
        return ""
    env: dict[str, Any] = {}
    if github_user and github_repo:
        repo = f"https://github.com/{github_user}/{github_repo}"
        env = {"link_base": f"{repo}/blob/HEAD/", "image_base": f"{repo}/raw/HEAD/"}
    return _sanitize(_README_MD.render(text, env), env.get("link_base"), env.get("image_base"))


def render_description(html: str | None) -> str:
    """Sanitizes an AnkiWeb description: the author's HTML, with absolute URLs; links open in a new tab."""
    return _sanitize(html, None, None, {"a": {"target": "_blank"}}) if html else ""


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
