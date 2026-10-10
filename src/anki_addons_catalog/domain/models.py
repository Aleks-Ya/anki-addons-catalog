from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

AI_PROVENANCE = "AI-generated summary; may contain mistakes."


class AddonCard(BaseModel):
    id: int
    title: str
    url: str
    rating: int = 0
    likes: int = 0
    dislikes: int = 0
    update_date: str | None = None
    anki_version: str | None = None
    ai_summary: str | None = None
    github_user: str | None = None
    github_repo: str | None = None
    github_stars: int | None = None
    github_archived: bool | None = None
    license: str | None = None

    @classmethod
    def from_details(cls, details: dict[str, Any]) -> "AddonCard":
        """Builds a card from a get_addon record (AddonDetails)."""
        anki_web = details["anki_web"]
        github = details.get("github") or {}
        ai = details.get("ai") or {}
        return cls(
            id=details["id"], title=anki_web["title"], url=anki_web["addon_page_url"],
            rating=anki_web.get("rating", 0), likes=anki_web.get("likes", 0), dislikes=anki_web.get("dislikes", 0),
            update_date=anki_web.get("update_date"), anki_version=anki_web.get("anki_version"),
            ai_summary=ai.get("summary"), github_user=github.get("user"), github_repo=github.get("repo"),
            github_stars=github.get("stars"), github_archived=github.get("archived"), license=github.get("license"),
        )


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
