import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel

AI_PROVENANCE = "AI-generated summary; may contain mistakes."
OBSOLETE_TAG = "obsolete"
PAID_TAG = "paid"
AI_TAG = "ai"
SORTS = {"rating": "Best rated", "likes": "Likes", "stars": "GitHub stars", "update_date": "Recently updated",
         "anki_version": "Newest Anki version"}
MIN_RATINGS = (10, 50, 200)
RECENT_DAYS = 730
MAX_TAGS = 10
MAX_LANGUAGES = 10
MAX_KEYWORD_CHARS = 100
_ANKI_VERSION = re.compile(r"\d+(\.\d+){1,2}([ab]\d+)?")
_TAG = re.compile(r"[a-z0-9][a-z0-9-]*")
_LANGUAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 +#.'-]{0,39}")  # GitHub Linguist names, e.g. C++, Common Lisp


class AddonCard(BaseModel):
    id: int
    title: str
    url: str
    rating: int = 0
    likes: int = 0
    dislikes: int = 0
    approval: float | None = None  # Wilson lower bound of likes among votes; absent in get_addon records
    update_date: str | None = None
    anki_version: str | None = None
    ai_summary: str | None = None
    ai_tags: list[str] = []
    ai_development: dict[str, list[str]] | None = None  # AI coding evidence: tooling (GitHub repo), declaration (description)
    github_user: str | None = None
    github_repo: str | None = None
    github_stars: int | None = None
    github_archived: bool | None = None
    license: str | None = None
    forked_from: int | None = None  # the addon this one was forked from
    forks: list[int] = []  # addons forked from this one
    duplicate_of: int | None = None  # the addon this one is a copy of (the same package)
    duplicates: list[int] = []  # copies of this addon

    @classmethod
    def from_details(cls, details: dict[str, Any]) -> "AddonCard":
        """Builds a card from a get_addon record (AddonDetails)."""
        anki_web = details["anki_web"]
        github = details.get("github") or {}
        ai = details.get("ai") or {}
        evidence = {"tooling": github.get("ai_tooling_markers") or [],
                    "declaration": anki_web.get("ai_declaration_markers") or []}
        return cls(
            id=details["id"], title=anki_web["title"], url=anki_web["addon_page_url"],
            rating=anki_web.get("rating", 0), likes=anki_web.get("likes", 0), dislikes=anki_web.get("dislikes", 0),
            update_date=anki_web.get("update_date"), anki_version=anki_web.get("anki_version"),
            ai_summary=ai.get("summary"), ai_tags=ai.get("tags") or [], github_user=github.get("user"), github_repo=github.get("repo"),
            github_stars=github.get("stars"), github_archived=github.get("archived"),
            license=(details.get("license") or {}).get("spdx_id"),
            forked_from=(details.get("forked_from") or {}).get("id"), forks=details.get("forks") or [],
            duplicate_of=(details.get("duplicate_of") or {}).get("id"), duplicates=details.get("duplicates") or [],
            ai_development={k: v for k, v in evidence.items() if v} or None,
        )


def ai_use_reasons(ai_development: dict[str, list[str]] | None, ai_tags: list[str]) -> list[str]:
    """Why an addon counts as built with AI, one sentence per signal; empty when there is no signal.

    An addon with AI features counts too: its author uses AI, so most likely also to write the code."""
    evidence = ai_development or {}
    reasons: list[str] = []
    if evidence.get("tooling"):
        reasons.append(f"The GitHub repository has files of AI coding tools: {', '.join(evidence['tooling'])}.")
    if evidence.get("declaration"):
        reasons.append(f"The description says that AI was used: {', '.join(evidence['declaration'])}.")
    if AI_TAG in ai_tags:
        reasons.append("The addon has AI features.")
    return reasons


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    is_error: bool
    text: str
    structured: Any = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "pause_turn", "other"]


@dataclass
class LlmTurn:
    """One model response. `assistant_content` is opaque and is sent back unchanged in the next request."""
    assistant_content: Any
    text: str
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    usage: Usage = field(default_factory=Usage)
    model: str = ""  # the model that answered (with the refusal fallback it can differ from the requested one)


EventType = Literal["status", "text", "addons", "answer", "error", "done"]


@dataclass(frozen=True)
class AnswerEvent:
    type: EventType
    data: Any = None


class SearchFilters(BaseModel):
    """Visitor filters of the search page; they narrow the keyword results, browsing and the AI answer.

    Defaults are what an empty URL means: obsolete addons are hidden, everything else is shown."""
    anki: str | None = None
    tags: list[str] = []
    languages: list[str] = []  # the addon must contain all of them
    show_obsolete: bool = False
    hide_paid: bool = False
    hide_forks: bool = False
    recent: bool = False  # updated on AnkiWeb in the last two years
    not_archived: bool = False
    has_github: bool = False
    min_rating: int | None = None
    keywords: str | None = None  # browsing only: full-text words that narrow the list, in the chosen sort order
    sort: str = "rating"  # browsing only: a text query always ranks by relevance

    @classmethod
    def parse(cls, params: Any) -> "SearchFilters":
        """From URL query parameters (a Starlette QueryParams or a multi-dict); invalid values are dropped."""
        anki = (params.get("anki") or "").strip()
        tags = [t for t in dict.fromkeys(t.strip().lower() for t in params.getlist("tag")) if _TAG.fullmatch(t)]
        languages: dict[str, str] = {}  # by lower case: GitHub Linguist names are matched ignoring case
        for lang in (lang.strip() for lang in params.getlist("lang")):
            if _LANGUAGE.fullmatch(lang):
                languages.setdefault(lang.lower(), lang)
        rating = params.get("rating", "")
        keywords = " ".join((params.get("kw") or "").split())[:MAX_KEYWORD_CHARS].strip()
        return cls(anki=anki if _ANKI_VERSION.fullmatch(anki) else None, tags=tags[:MAX_TAGS],
                   languages=list(languages.values())[:MAX_LANGUAGES],
                   show_obsolete=params.get("obsolete") == "1", hide_paid=params.get("nopaid") == "1",
                   hide_forks=params.get("nofork") == "1",
                   recent=params.get("recent") == "1", not_archived=params.get("active") == "1",
                   has_github=params.get("github") == "1",
                   min_rating=int(rating) if rating.isdigit() and int(rating) in MIN_RATINGS else None,
                   keywords=keywords or None,
                   sort=params.get("sort") if params.get("sort") in SORTS else "rating")

    def params(self, browse: bool = True) -> list[tuple[str, str]]:
        """The URL query parameters, the inverse of `parse` (defaults are left out); `browse=False` leaves out the
        browsing-only keywords and sort order."""
        items: list[tuple[str, str]] = [("anki", self.anki)] if self.anki else []
        items += [("tag", t) for t in self.tags]
        items += [("lang", lang) for lang in self.languages]
        flags = {"obsolete": self.show_obsolete, "nopaid": self.hide_paid, "nofork": self.hide_forks, "recent": self.recent,
                 "active": self.not_archived, "github": self.has_github}
        items += [(name, "1") for name, on in flags.items() if on]
        if self.min_rating:
            items.append(("rating", str(self.min_rating)))
        if browse and self.keywords:
            items.append(("kw", self.keywords))
        if browse and self.sort != "rating":
            items.append(("sort", self.sort))
        return items

    def chips(self) -> list[tuple[str, "SearchFilters"]]:
        """Each active filter as a label and the filters without it, for removable chips."""
        chips: list[tuple[str, SearchFilters]] = []
        if self.keywords:
            chips.append((f"Keywords: {self.keywords}", self.model_copy(update={"keywords": None})))
        if self.anki:
            chips.append((f"Anki {self.anki}", self.model_copy(update={"anki": None})))
        chips += [(t, self.model_copy(update={"tags": [x for x in self.tags if x != t]})) for t in self.tags]
        chips += [(f"Language: {lang}", self.model_copy(update={"languages": [x for x in self.languages if x != lang]}))
                  for lang in self.languages]
        labels = {"show_obsolete": "Obsolete shown", "hide_paid": "No paid", "hide_forks": "No forks", "recent": "Updated in 2 years",
                  "not_archived": "Not archived", "has_github": "On GitHub"}
        chips += [(label, self.model_copy(update={name: False})) for name, label in labels.items()
                  if getattr(self, name)]
        if self.min_rating:
            chips.append((f"≥ {self.min_rating} votes", self.model_copy(update={"min_rating": None})))
        return chips

    def describe(self) -> str:
        """The active filters in words, for the AI; obsolete addons are hidden unless shown."""
        labels = [label for label, _ in self.chips()]
        return ", ".join(labels if self.show_obsolete else ["obsolete hidden", *labels])

    def tool_args(self, today: date) -> dict[str, Any]:
        """Arguments of the search_addons and filter_addons MCP tools."""
        args: dict[str, Any] = {}
        if self.anki:
            args["compatible_with_anki"] = self.anki
        if self.tags:
            args["tags"] = list(self.tags)
        if self.languages:
            args["language"] = list(self.languages)
        exclude = ([] if self.show_obsolete else [OBSOLETE_TAG]) + ([PAID_TAG] if self.hide_paid else [])
        if exclude:
            args["exclude_tags"] = exclude
        if self.hide_forks:
            args["is_fork"] = False
        if self.recent:
            args["updated_after"] = (today - timedelta(days=RECENT_DAYS)).isoformat()
        if self.not_archived:
            args["archived"] = False
        if self.has_github:
            args["has_github"] = True
        if self.min_rating:
            args["min_rating"] = self.min_rating
        return args
