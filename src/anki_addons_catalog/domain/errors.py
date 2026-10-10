class CatalogUnavailable(Exception):
    """The MCP server cannot be reached."""


class ToolFailed(Exception):
    """An MCP tool returned an error."""

    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message
