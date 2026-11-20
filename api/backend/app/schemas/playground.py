"""Pydantic schemas for /playground and /playground/execute endpoints."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class PlaygroundRequest(BaseModel):
    """Payload for POST /playground."""

    mode: Literal["explain", "solve"] = Field(
        ...,
        description="'explain' — user provides code to be explained; 'solve' — user describes a problem",
    )
    language: Literal["python", "java", "cpp"] = Field(
        default="python",
        description="Programming language for the solution",
    )
    code: Optional[str] = Field(
        default=None,
        max_length=8000,
        description="Pasted code (required for mode='explain')",
    )
    problem: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Problem description (required for mode='solve')",
    )
    custom_input: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional custom test input for execution context",
    )

    model_config = ConfigDict(extra="ignore")


class PlaygroundResponse(BaseModel):
    """Response structure for POST /playground."""

    status: Literal["ok", "error"]
    mode: Literal["explain", "solve"]
    language: Literal["python", "java", "cpp"]
    solution_code: str = Field(default="", description="The solution or explained code")
    explanation: str = Field(default="", description="Step-by-step explanation text")
    approach: str = Field(default="", description="Brief approach summary (beginner-friendly)")
    source: Literal["db", "llm", "passthrough"] = Field(
        default="llm",
        description="Where the solution came from: existing DB, LLM generation, or passthrough",
    )
    error: Optional[str] = Field(default=None, description="Error message if status='error'")


class ExecuteRequest(BaseModel):
    """Payload for POST /playground/execute."""

    language: Literal["python", "java", "cpp"] = Field(
        default="python",
        description="Programming language to execute",
    )
    code: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Code to execute in the sandbox",
    )
    custom_input: Optional[str] = Field(
        default="",
        max_length=2000,
        description="Standard input to provide to the running program",
    )
    timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Maximum execution time allowed in seconds",
    )

    model_config = ConfigDict(extra="ignore")


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


class ExecuteResponse(BaseModel):
    """Response structure for POST /playground/execute."""

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


