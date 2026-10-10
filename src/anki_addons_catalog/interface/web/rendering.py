from typing import Any

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict


def _link_open(self: RendererHTML, tokens: list[Token], idx: int, options: OptionsDict, env: EnvType) -> str:
    token = tokens[idx]
    href = str(token.attrGet("href") or "")
    if href.startswith(("http://", "https://")):
        token.attrSet("rel", "nofollow noopener noreferrer")
        token.attrSet("target", "_blank")
    return self.renderToken(tokens, idx, options, env)


def _markdown() -> MarkdownIt:
    """CommonMark + tables with raw HTML disabled: READMEs and AI answers are untrusted input."""
    md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").enable("strikethrough")
    md.add_render_rule("link_open", _link_open)
    return md


_MD = _markdown()


def render_markdown(text: str | None) -> str:
    return _MD.render(text) if text else ""


def compact_number(value: Any) -> str:
    if not isinstance(value, int | float):
        return "–"
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return str(value)
