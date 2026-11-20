"""Pydantic schemas for the code execution engine (Phase 2)."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class TraceStep(BaseModel):
    """A single step in the execution trace."""

    step: int = Field(..., description="1-based step index")
    line_number: int = Field(..., description="Source line number (1-based)")
    local_vars: Dict[str, Any] = Field(
        default_factory=dict,
        description="Snapshot of local variable values at this step",
    )
    description: str = Field(default="", description="Human-readable step description")
    pointers: Dict[str, int] = Field(
        default_factory=dict,
        description="Detected pointers/indices (e.g. left, right, i, j, mid)",
    )
    active_array: Optional[str] = Field(
        default=None,
        description="Name of the array being focused or modified",
    )
    window: Optional[List[int]] = Field(
        default=None,
        description="Active range/window [start, end] if detected",
    )
    accessed_indices: List[int] = Field(
        default_factory=list,
        description="Indices being accessed or compared at this step",
    )
    operation_type: str = Field(
        default="step",
        description="Category of operation: access, compare, swap, update, expand, shrink, return",
    )
    explanation: str = Field(
        default="",
        description="Beginner-friendly explanation of why this line ran and what happened",
    )
    changed_vars: List[str] = Field(
        default_factory=list,
        description="List of variable names that changed in this step",
    )

    model_config = ConfigDict(extra="ignore")


class ExecutionResult(BaseModel):
    """Full result of executing user code in the sandbox."""

    status: Literal["ok", "error", "timeout", "compile_error", "unavailable"] = Field(
        ..., description="Execution outcome"
    )
    stdout: str = Field(default="", description="Captured standard output")
    stderr: str = Field(default="", description="Captured standard error / compiler output")
    exit_code: int = Field(default=0, description="Process exit code")
    execution_time_ms: float = Field(default=0.0, description="Wall-clock time in milliseconds")
    timed_out: bool = Field(default=False, description="True if execution exceeded the timeout")
    trace_steps: List[TraceStep] = Field(
        default_factory=list,
        description="Step-by-step execution trace (Python only)",
    )
    trace_available: bool = Field(
        default=False,
        description="True when trace_steps contains real trace data",
    )
    language: str = Field(..., description="Language that was executed")
    language_unavailable: bool = Field(
        default=False,
        description="True when the runtime/compiler is not installed on this system",
    )

    model_config = ConfigDict(extra="ignore")
