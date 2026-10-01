from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Abstract base class for all NEXUS specialized agents."""

    def __init__(self, name: str, role: str) -> None:
        self.name = name
        self.role = role

    @abstractmethod
    async def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Process current state and return state mutations."""
        pass

    def __repr__(self) -> str:
        return f"<Agent: {self.name} | Role: {self.role}>"
