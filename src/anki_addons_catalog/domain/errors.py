from datetime import datetime


class CatalogUnavailable(Exception):
    """The MCP server cannot be reached."""


class ToolFailed(Exception):
    """An MCP tool returned an error."""

    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message


class LlmQuotaExhausted(Exception):
    """The LLM provider refuses requests until `until` (UTC), e.g. at the workspace spend limit; None if not stated."""

    def __init__(self, message: str, until: datetime | None) -> None:
        super().__init__(message)
        self.until = until
