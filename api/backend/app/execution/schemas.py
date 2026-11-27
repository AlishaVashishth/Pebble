"""Pydantic schemas for the code execution engine (Phase 2 & Phase 1 Universal DSA)."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class CallStackFrame(BaseModel):
    """Snapshot of a single function call frame in recursion."""

    func_name: str = Field(..., description="Function name")
    args: Dict[str, Any] = Field(default_factory=dict, description="Arguments passed to this frame")
    return_value: Optional[Any] = Field(default=None, description="Return value if evaluated")
    depth: int = Field(default=0, description="Call depth (0-based)")
    frame_id: Optional[str] = Field(default=None, description="Unique ID for this invocation frame")
    parent_frame_id: Optional[str] = Field(default=None, description="ID of calling frame")
    local_vars: Dict[str, Any] = Field(default_factory=dict, description="Local variables for this frame")
    line_number: Optional[int] = Field(default=None, description="Current line number inside this frame")
    status: Optional[str] = Field(default="active", description="Frame status: 'active' or 'returning'")

    model_config = ConfigDict(extra="ignore")


class LinkedListNode(BaseModel):
    """Snapshot of a linked list node for graph/list visualization."""

    id: str = Field(..., description="Unique node ID or memory address")
    val: Any = Field(..., description="Node value")
    next_id: Optional[str] = Field(default=None, description="ID of next node")

    model_config = ConfigDict(extra="ignore")


class TreeNode(BaseModel):
    """Snapshot of a binary tree node."""

    id: str = Field(..., description="Unique node ID")
    val: Any = Field(..., description="Node value")
    left_id: Optional[str] = Field(default=None, description="ID of left child")
    right_id: Optional[str] = Field(default=None, description="ID of right child")

    model_config = ConfigDict(extra="ignore")


class GraphData(BaseModel):
    """Snapshot of a graph state."""

    nodes: List[Dict[str, Any]] = Field(default_factory=list, description="Graph nodes with id and status")
    edges: List[Dict[str, Any]] = Field(default_factory=list, description="Graph edges [source, target]")
    visited: List[str] = Field(default_factory=list, description="List of visited node IDs")
    current_node: Optional[str] = Field(default=None, description="Node currently being explored")

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
        description="Category of operation: access, compare, swap, update, expand, shrink, push, pop, insert, delete, visit, return, call",
    )
    explanation: str = Field(
        default="",
        description="Beginner-friendly explanation of why this line ran and what happened",
    )
    changed_vars: List[str] = Field(
        default_factory=list,
        description="List of variable names that changed in this step",
    )

    # ── Universal DSA Structure Enriched Fields ──
    data_structure_type: Optional[str] = Field(
        default=None,
        description="Detected primary DSA structure: array, string, hashmap, set, stack, queue, linked_list, tree, graph, recursion",
    )
    string_view: Optional[Dict[str, Any]] = Field(
        default=None,
        description="String state with characters and pointers",
    )
    hash_map_view: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Map/Dict/Set entries with highlight flags",
    )
    stack_view: Optional[List[Any]] = Field(
        default=None,
        description="Items in stack (bottom to top)",
    )
    queue_view: Optional[List[Any]] = Field(
        default=None,
        description="Items in queue (front to rear)",
    )
    linked_list_view: Optional[List[LinkedListNode]] = Field(
        default=None,
        description="Linked list node chain snapshot",
    )
    tree_view: Optional[List[TreeNode]] = Field(
        default=None,
        description="Tree nodes and connection snapshot",
    )
    call_stack: Optional[List[CallStackFrame]] = Field(
        default=None,
        description="Recursion call stack frames",
    )
    call_depth: Optional[int] = Field(
        default=None,
        description="Current recursion/call stack depth",
    )
    event_type: Optional[str] = Field(
        default=None,
        description="Event category: call, line, return",
    )
    return_value: Optional[Any] = Field(
        default=None,
        description="Return value if step is a return event",
    )
    graph_view: Optional[GraphData] = Field(
        default=None,
        description="Graph nodes, edges and traversal progress",
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
        description="Step-by-step execution trace",
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
