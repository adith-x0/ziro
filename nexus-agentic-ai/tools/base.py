import time
from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Abstract base class for all operational tools and simulated actuators."""

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

    @abstractmethod
    async def run(self, **kwargs: Any) -> dict[str, Any]:
        """Execute tool logic with kwargs and return structured result."""
        pass

    async def execute_with_timing(self, **kwargs: Any) -> dict[str, Any]:
        """Execute tool with latency measurement and error wrapping."""
        start_time = time.time()
        try:
            result = await self.run(**kwargs)
            duration_ms = (time.time() - start_time) * 1000.0
            return {
                "tool_name": self.name,
                "status": "success",
                "execution_time_ms": round(duration_ms, 2),
                "data": result,
            }
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000.0
            return {
                "tool_name": self.name,
                "status": "failed",
                "execution_time_ms": round(duration_ms, 2),
                "error": str(exc),
            }
