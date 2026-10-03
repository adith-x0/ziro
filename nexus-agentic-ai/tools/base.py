"""NEXUS Tool Base Framework & Execution Contracts.

Provides:
- `BaseNexusTool[TInput, TOutput]`: Generic base class with typed I/O, timeouts,
  risk classifications, and approval-token safety enforcement.
- `ToolResult[TOutput]`: Standardized execution result containing structured metadata.
- `ToolError`: Structured failure model.
- `BaseTool`: Legacy base class retained for backwards compatibility.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger("nexus.tools")

TInput = TypeVar("TInput", bound=BaseModel)
TOutput = TypeVar("TOutput", bound=BaseModel)

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
SIMULATION_TAG = "simulation/mock environment"


# -----------------------------------------------------------------------------
# Structured Tool Result & Error Schemas
# -----------------------------------------------------------------------------
class ToolError(BaseModel):
    """Structured error descriptor returned upon tool execution failure."""

    model_config = ConfigDict(extra="forbid")

    error_code: str = Field(..., description="Unique machine-readable error code")
    message: str = Field(..., description="Human-readable description of failure")
    details: dict[str, Any] = Field(default_factory=dict, description="Diagnostic payload")
    retryable: bool = Field(default=False, description="Whether caller may safely retry")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ToolResult(BaseModel, Generic[TOutput]):
    """Standardized result returned by all NEXUS tool executions."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tool_name: str
    success: bool = Field(..., description="True if execution succeeded, False otherwise")
    status: Literal["success", "error"] = Field(..., description="'success' or 'error'")
    output: TOutput | None = Field(default=None, description="Typed output payload upon success")
    data: TOutput | None = Field(
        default=None, description="Alias for output for backward compatibility"
    )
    error: ToolError | None = Field(default=None, description="Structured error upon failure")
    error_code: str | None = Field(default=None, description="Quick-access machine error code")
    simulation_status: str = Field(
        default=SIMULATION_TAG,
        description="Explicit indicator of simulated execution environment",
    )
    environment: str = Field(
        default=SIMULATION_TAG,
        description="Environment tag e.g. simulation/mock environment",
    )
    is_simulation: bool = Field(default=True, description="Strictly true for all mock tools")
    execution_time_ms: float = Field(
        default=0.0,
        description="Execution duration in milliseconds",
    )
    execution_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Telemetry containing latency, started_at, completed_at, and risk level",
    )


# Alias ToolExecutionResult to ToolResult for backward compatibility
ToolExecutionResult = ToolResult


# -----------------------------------------------------------------------------
# Modern Base NEXUS Tool Class
# -----------------------------------------------------------------------------
class BaseNexusTool(ABC, Generic[TInput, TOutput]):
    """Abstract base class for all typed, safe NEXUS tools with dependency injection."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: type[TInput],
        output_schema: type[TOutput],
        risk_level: RiskLevel = "LOW",
        requires_approval: bool = False,
        timeout_seconds: float = 5.0,
        is_simulation: bool = True,
        provider: Any = None,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.risk_level: RiskLevel = risk_level
        self.requires_approval: bool = requires_approval
        self.timeout_seconds: float = timeout_seconds
        self.is_simulation: bool = is_simulation
        self.provider = provider
        self.environment_tag = SIMULATION_TAG
        self._logger = logging.getLogger(f"nexus.tools.{name}")

    @abstractmethod
    async def _execute_internal(self, validated_input: TInput) -> TOutput:
        """Core execution logic implemented by tool or injected provider."""
        pass

    async def execute(
        self,
        input_data: TInput | dict[str, Any],
        approval_token: str | None = None,
    ) -> ToolResult[TOutput]:
        """Safely validates inputs, enforces approval tokens, handles timeouts, and captures telemetry."""
        started_at = datetime.now(UTC)
        start_perf = time.perf_counter()

        def _make_metadata(duration_ms: float) -> dict[str, Any]:
            return {
                "execution_time_ms": round(duration_ms, 2),
                "started_at": started_at.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "risk_level": self.risk_level,
                "requires_approval": self.requires_approval,
                "timeout_seconds": self.timeout_seconds,
            }

        # 1. Human-In-The-Loop Approval Token Enforcement
        # High/Medium risk actions cannot bypass the policy gatekeeper
        token = approval_token
        if isinstance(input_data, dict) and not token:
            token = input_data.get("approval_token")
        elif hasattr(input_data, "approval_token") and not token:
            token = getattr(input_data, "approval_token", None)

        if self.requires_approval and (not token or not str(token).strip()):
            duration_ms = (time.perf_counter() - start_perf) * 1000.0
            self._logger.warning(
                f"[{self.name}] Intercepted direct call: Action requires human approval token but none was provided."
            )
            return ToolResult[TOutput](
                tool_name=self.name,
                success=False,
                status="error",
                error_code="APPROVAL_TOKEN_REQUIRED",
                error=ToolError(
                    error_code="APPROVAL_TOKEN_REQUIRED",
                    message=(
                        f"Action '{self.name}' is classified as {self.risk_level} risk and strictly "
                        "requires a validated commander approval token. Direct unauthenticated execution is forbidden."
                    ),
                    details={
                        "risk_level": self.risk_level,
                        "requires_approval": self.requires_approval,
                    },
                    retryable=False,
                ),
                simulation_status=self.environment_tag,
                environment=self.environment_tag,
                is_simulation=self.is_simulation,
                execution_time_ms=round(duration_ms, 2),
                execution_metadata=_make_metadata(duration_ms),
            )

        # 2. Input Validation
        try:
            if isinstance(input_data, dict):
                validated_input = self.input_schema.model_validate(input_data)
            else:
                validated_input = input_data
        except ValidationError as val_err:
            duration_ms = (time.perf_counter() - start_perf) * 1000.0
            self._logger.warning(f"[{self.name}] Input validation failed: {val_err}")
            return ToolResult[TOutput](
                tool_name=self.name,
                success=False,
                status="error",
                error_code="VALIDATION_ERROR",
                error=ToolError(
                    error_code="VALIDATION_ERROR",
                    message="Input failed schema validation bounds.",
                    details={"validation_errors": val_err.errors()},
                    retryable=False,
                ),
                simulation_status=self.environment_tag,
                environment=self.environment_tag,
                is_simulation=self.is_simulation,
                execution_time_ms=round(duration_ms, 2),
                execution_metadata=_make_metadata(duration_ms),
            )

        # 3. Execution with Timeout & Structured Error Handling
        try:
            self._logger.info(f"[{self.name}] Executing in {self.environment_tag}...")
            output = await asyncio.wait_for(
                self._execute_internal(validated_input),
                timeout=self.timeout_seconds,
            )
            duration_ms = (time.perf_counter() - start_perf) * 1000.0

            if not isinstance(output, self.output_schema):
                output = self.output_schema.model_validate(output)

            self._logger.info(f"[{self.name}] Completed successfully in {duration_ms:.2f}ms")
            return ToolResult[TOutput](
                tool_name=self.name,
                success=True,
                status="success",
                output=output,
                data=output,
                simulation_status=self.environment_tag,
                environment=self.environment_tag,
                is_simulation=self.is_simulation,
                execution_time_ms=round(duration_ms, 2),
                execution_metadata=_make_metadata(duration_ms),
            )

        except TimeoutError:
            duration_ms = (time.perf_counter() - start_perf) * 1000.0
            self._logger.error(f"[{self.name}] Timed out after {self.timeout_seconds}s")
            return ToolResult[TOutput](
                tool_name=self.name,
                success=False,
                status="error",
                error_code="TIMEOUT_ERROR",
                error=ToolError(
                    error_code="TIMEOUT_ERROR",
                    message=f"Tool execution timed out after {self.timeout_seconds} seconds.",
                    details={"timeout_seconds": self.timeout_seconds},
                    retryable=True,
                ),
                simulation_status=self.environment_tag,
                environment=self.environment_tag,
                is_simulation=self.is_simulation,
                execution_time_ms=round(duration_ms, 2),
                execution_metadata=_make_metadata(duration_ms),
            )

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_perf) * 1000.0
            self._logger.error(f"[{self.name}] Execution error: {exc}", exc_info=True)
            return ToolResult[TOutput](
                tool_name=self.name,
                success=False,
                status="error",
                error_code="EXECUTION_ERROR",
                error=ToolError(
                    error_code="EXECUTION_ERROR",
                    message=str(exc),
                    details={"exception_type": type(exc).__name__},
                    retryable=False,
                ),
                simulation_status=self.environment_tag,
                environment=self.environment_tag,
                is_simulation=self.is_simulation,
                execution_time_ms=round(duration_ms, 2),
                execution_metadata=_make_metadata(duration_ms),
            )


# -----------------------------------------------------------------------------
# Legacy BaseTool (Retained for Backwards Compatibility)
# -----------------------------------------------------------------------------
class BaseTool(ABC):
    """Legacy abstract base class for existing simulated actuators."""

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
