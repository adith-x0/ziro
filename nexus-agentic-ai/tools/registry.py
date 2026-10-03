"""NEXUS Central Tool Registry.

Provides registration, lookup, JSON Schema introspection, and consistent execution:
`tool_registry.execute(tool_name, input_data, approval_token=None)`
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from tools.base import BaseNexusTool, ToolError, ToolExecutionResult, ToolResult

logger = logging.getLogger("nexus.tools.registry")

__all__ = [
    "ToolRegistry",
    "default_tool_registry",
    "register_default_tools",
    "BaseNexusTool",
    "ToolResult",
    "ToolExecutionResult",
    "ToolError",
]


class ToolRegistry:
    """Central registry for discovering and safely executing NEXUS operational tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseNexusTool[Any, Any]] = {}

    def register(self, tool: BaseNexusTool[Any, Any]) -> None:
        """Registers a BaseNexusTool instance by its unique name."""
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool registration for '{tool.name}'")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool '{tool.name}' ({tool.environment_tag})")

    def get(self, name: str) -> BaseNexusTool[Any, Any]:
        """Retrieves a registered tool by name or raises KeyError."""
        if name not in self._tools:
            raise KeyError(
                f"Tool '{name}' is not registered in ToolRegistry. Available: {list(self._tools.keys())}"
            )
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Checks if a tool exists in the registry."""
        return name in self._tools

    def list_tools(self) -> list[str]:
        """Returns sorted list of all registered tool names."""
        return sorted(list(self._tools.keys()))

    def get_tool_descriptions(self) -> list[dict[str, Any]]:
        """Returns JSON schema descriptors of all tools for LLM agent binding."""
        descriptors = []
        for name, tool in self._tools.items():
            descriptors.append(
                {
                    "name": name,
                    "description": tool.description,
                    "environment": tool.environment_tag,
                    "is_simulation": tool.is_simulation,
                    "risk_level": tool.risk_level,
                    "requires_approval": tool.requires_approval,
                    "timeout_seconds": tool.timeout_seconds,
                    "input_schema": tool.input_schema.model_json_schema(),
                    "output_schema": tool.output_schema.model_json_schema(),
                }
            )
        return descriptors

    async def execute(
        self,
        tool_name: str,
        input_data: dict[str, Any] | BaseModel,
        approval_token: str | None = None,
    ) -> ToolResult[Any]:
        """Consistent execution entrypoint for all agent tool invocations."""
        tool = self.get(tool_name)
        return await tool.execute(input_data, approval_token=approval_token)

    async def execute_tool(
        self,
        name: str,
        input_data: dict[str, Any] | BaseModel,
        approval_token: str | None = None,
    ) -> ToolResult[Any]:
        """Backward-compatible alias for execute()."""
        return await self.execute(name, input_data, approval_token=approval_token)


def register_default_tools(registry: ToolRegistry | None = None) -> ToolRegistry:
    """Instantiates and registers all 11 concrete tools with deterministic mock providers."""
    from tools.implementations import (
        AmbulanceReservationTool,
        AuditLoggingTool,
        GeolocationTool,
        HospitalStatusTool,
        ImageAnalysisTool,
        IncidentReportsTool,
        IncidentStatusUpdateTool,
        NotificationsTool,
        ResourceSearchTool,
        RoutingTool,
        WeatherTool,
    )

    target = registry or default_tool_registry

    tools_to_register: list[BaseNexusTool[Any, Any]] = [
        WeatherTool(),
        IncidentReportsTool(),
        ImageAnalysisTool(),
        GeolocationTool(),
        RoutingTool(),
        ResourceSearchTool(),
        HospitalStatusTool(),
        NotificationsTool(),
        AmbulanceReservationTool(),
        IncidentStatusUpdateTool(),
        AuditLoggingTool(),
    ]

    for t in tools_to_register:
        target.register(t)

    return target


# Global default registry singleton
default_tool_registry = ToolRegistry()
register_default_tools(default_tool_registry)
