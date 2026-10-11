"""The tool interface and a name lookup for it.

A tool is a name, a description, and a parameter schema a caller can show to
a model, plus an execute method. The registry finds a tool by name. A failed
call becomes text the caller can pass on, instead of leaving the registry.
"""

from __future__ import annotations


class Tool:
    name: str
    description: str
    parameters: dict
    deferred = False
    needs_approval = False

    def execute(self, **arguments) -> str:
        raise NotImplementedError

    def preview(self, **arguments) -> str:
        """What `execute` would change, without changing it. Raises when the call would fail."""
        raise NotImplementedError

    def revealed(self, arguments: dict, result: str) -> list[str]:
        """Tool names this successful call makes visible on the next step."""
        return []


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools = {tool.name: tool for tool in tools}

    def schemas(self, visible: set[str] | None = None) -> list[dict]:
        """Schemas for this request. Deferred tools stay out until this run names them."""
        visible = visible or set()
        return [
            self._schema(tool)
            for tool in self._tools.values()
            if not tool.deferred or tool.name in visible
        ]

    def deferred(self) -> list[tuple[str, str]]:
        """Name and description of tools whose schemas stay out until revealed."""
        return [(tool.name, tool.description) for tool in self._tools.values() if tool.deferred]

    def tool_describe(self, name: str) -> dict:
        """The schema for one registered tool."""
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(name)
        return self._schema(tool)

    def _schema(self, tool: Tool) -> dict:
        return {"name": tool.name, "description": tool.description, "parameters": tool.parameters}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def needs_approval(self, name: str) -> bool:
        tool = self._tools.get(name)
        return tool is not None and tool.needs_approval

    def preview(self, name: str, arguments: dict | None = None) -> str:
        """The preview text, or an error in the same form as `call`."""
        tool = self._tools.get(name)
        if tool is None:
            return f"error: unknown tool: {name}"
        missing = _missing_required(tool, arguments)
        if missing:
            return missing
        try:
            return tool.preview(**(arguments or {}))
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"

    def call(self, name: str, arguments: dict | None = None) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"error: unknown tool: {name}"
        missing = _missing_required(tool, arguments)
        if missing:
            return missing
        try:
            return tool.execute(**(arguments or {}))
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"


def _missing_required(tool: Tool, arguments: dict | None) -> str:
    """A tool error when a schema-required argument was not sent. Empty string still counts as sent."""
    required = tool.parameters.get("required") or []
    given = arguments or {}
    missing = [name for name in required if name not in given or given[name] is None]
    if not missing:
        return ""
    return f"error: ValueError: {tool.name} is missing required {', '.join(missing)}"
