"""
Python execution tracer for Pebble Playground 2.0 (Phase 1 Universal DSA).

Instruments user Python code with sys.settrace() to capture line-by-line
snapshots of:
  - Local variables & call stack frames (recursion depth)
  - String manipulation & substrings
  - Arrays, lists, matrices
  - Dictionaries / HashMaps & frequency counters
  - Stacks and queues (lists or deque)
  - Linked list nodes (val, next references)
  - Tree nodes (val, left, right)
  - Graph structures (adjacency list / matrix)

Emits trace events as PEBBLE_TRACE:<json> stdout lines.
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any, Dict, List, Optional

# Prefix used to tag trace JSON lines in the combined stdout stream
_TRACE_PREFIX = "PEBBLE_TRACE:"

# How many trace steps to capture before stopping
_MAX_TRACE_STEPS = 600

# Variable value repr length limit
_MAX_REPR_LEN = 120


def _is_linked_list_node(val: Any) -> bool:
    """Check if object behaves like a singly/doubly linked list node."""
    if val is None or not hasattr(val, "__dict__"):
        return False
    d = val.__dict__
    return ("val" in d or "value" in d or "data" in d) and ("next" in d)


def _is_tree_node(val: Any) -> bool:
    """Check if object behaves like a binary tree node."""
    if val is None or not hasattr(val, "__dict__"):
        return False
    d = val.__dict__
    return ("val" in d or "value" in d or "data" in d) and ("left" in d or "right" in d)


def _extract_linked_list(head: Any, max_nodes: int = 15) -> List[Dict[str, Any]]:
    """Traverse a linked list into a serialized array of nodes with cycle protection."""
    nodes = []
    curr = head
    visited_ids = set()

    while curr is not None and len(nodes) < max_nodes:
        node_id = str(id(curr))
        if node_id in visited_ids:
            # Cycle detected
            val = getattr(curr, "val", getattr(curr, "value", getattr(curr, "data", None)))
            nodes.append({"id": node_id, "val": _safe_repr(val), "next_id": node_id, "cycle": True})
            break
        visited_ids.add(node_id)
        val = getattr(curr, "val", getattr(curr, "value", getattr(curr, "data", None)))
        next_node = getattr(curr, "next", None)
        next_id = str(id(next_node)) if next_node is not None else None
        nodes.append({"id": node_id, "val": _safe_repr(val), "next_id": next_id})
        curr = next_node

    return nodes


def _extract_tree(root: Any, max_nodes: int = 25) -> List[Dict[str, Any]]:
    """Traverse a binary tree via BFS into serialized nodes."""
    if root is None:
        return []
    nodes = []
    queue = [root]
    visited_ids = set()

    while queue and len(nodes) < max_nodes:
        curr = queue.pop(0)
        if curr is None:
            continue
        node_id = str(id(curr))
        if node_id in visited_ids:
            continue
        visited_ids.add(node_id)

        val = getattr(curr, "val", getattr(curr, "value", getattr(curr, "data", None)))
        left = getattr(curr, "left", None)
        right = getattr(curr, "right", None)

        left_id = str(id(left)) if left is not None else None
        right_id = str(id(right)) if right is not None else None

        nodes.append({
            "id": node_id,
            "val": _safe_repr(val),
            "left_id": left_id,
            "right_id": right_id,
        })

        if left is not None:
            queue.append(left)
        if right is not None:
            queue.append(right)

    return nodes


def _safe_repr(value: Any, depth: int = 0) -> Any:
    """Convert any Python value into a clean JSON-serializable representation."""
    if depth > 3:
        return "<nested>"
    if isinstance(value, (bool, int, float, type(None))):
        return value
    if isinstance(value, str):
        return value[:_MAX_REPR_LEN]
    if isinstance(value, (list, tuple)):
        return [_safe_repr(v, depth + 1) for v in value[:30]]
    if isinstance(value, dict):
        return {str(k)[:40]: _safe_repr(v, depth + 1) for k, v in list(value.items())[:20]}
    if isinstance(value, set):
        return [_safe_repr(v, depth + 1) for v in list(value)[:30]]

    # Special handling for custom node classes
    if _is_linked_list_node(value):
        val = getattr(value, "val", getattr(value, "value", getattr(value, "data", None)))
        next_obj = getattr(value, "next", None)
        return {
            "__type__": "ListNode",
            "val": _safe_repr(val, depth + 1),
            "has_next": next_obj is not None,
            "node_id": str(id(value)),
        }
    if _is_tree_node(value):
        val = getattr(value, "val", getattr(value, "value", getattr(value, "data", None)))
        return {
            "__type__": "TreeNode",
            "val": _safe_repr(val, depth + 1),
            "node_id": str(id(value)),
        }

    try:
        r = repr(value)
        return r[:_MAX_REPR_LEN]
    except Exception:
        return "<unprintable>"


_SKIP_VARS = frozenset(
    {
        "__name__", "__doc__", "__package__", "__loader__", "__spec__",
        "__builtins__", "__file__", "__cached__", "__annotations__",
        "_pebble_tracer",
    }
)


def _is_skippable_var(val: Any) -> bool:
    """Check if variable is a function, method, module, or class definition."""
    return isinstance(
        val,
        (
            types.FunctionType,
            types.BuiltinFunctionType,
            types.MethodType,
            types.ModuleType,
            type,
        ),
    )


class _PebbleTracer:
    """sys.settrace-compatible tracer that captures multi-structure DSA states and call stacks."""

    def __init__(self, user_filename: str) -> None:
        self._filename = user_filename
        self._steps: int = 0
        self._last_line: Optional[int] = None
        self._last_vars_repr: Optional[str] = None
        self._last_event: Optional[str] = None
        self._frame_counter: int = 0
        self._active_frames: List[Dict[str, Any]] = []

    def _emit(self, line_no: int, frame: types.FrameType, event: str, arg: Any = None) -> None:
        if self._steps >= _MAX_TRACE_STEPS:
            return

        local_vars = frame.f_locals
        filtered = {
            k: _safe_repr(v)
            for k, v in local_vars.items()
            if k not in _SKIP_VARS and not k.startswith("__") and not _is_skippable_var(v)
        }

        # Check for linked list or tree root objects in locals
        linked_lists: Dict[str, Any] = {}
        trees: Dict[str, Any] = {}

        for k, v in local_vars.items():
            if _is_linked_list_node(v):
                linked_lists[k] = _extract_linked_list(v)
            elif _is_tree_node(v):
                trees[k] = _extract_tree(v)

        vars_repr = json.dumps(filtered, sort_keys=True)
        # Avoid duplicate step if line, vars, and event are unchanged
        if (
            line_no == self._last_line
            and vars_repr == self._last_vars_repr
            and event == self._last_event
            and not linked_lists
            and not trees
        ):
            return

        self._steps += 1
        self._last_line = line_no
        self._last_vars_repr = vars_repr
        self._last_event = event

        # Build snapshot of current call stack from active frames
        call_stack_snapshot: List[Dict[str, Any]] = []
        for depth_idx, f_info in enumerate(self._active_frames):
            f = f_info["frame"]
            is_top = (depth_idx == len(self._active_frames) - 1)

            args_dict = {}
            for arg_name in f.f_code.co_varnames[:f.f_code.co_argcount]:
                if arg_name in f.f_locals:
                    args_dict[arg_name] = _safe_repr(f.f_locals[arg_name])

            frame_locals = {
                k: _safe_repr(v)
                for k, v in f.f_locals.items()
                if k not in _SKIP_VARS and not k.startswith("__") and not _is_skippable_var(v)
            }

            status = "returning" if (is_top and event == "return") else "active"
            ret_val = _safe_repr(arg) if (is_top and event == "return") else None

            call_stack_snapshot.append({
                "func_name": f.f_code.co_name,
                "frame_id": f_info["frame_id"],
                "parent_frame_id": f_info["parent_frame_id"],
                "depth": depth_idx,
                "line_number": f.f_lineno,
                "args": args_dict,
                "local_vars": frame_locals,
                "status": status,
                "return_value": ret_val,
            })

        payload = {
            "step": self._steps,
            "line_number": line_no,
            "local_vars": filtered,
            "event": event,
            "event_type": event,
            "operation_type": "call" if event == "call" else ("return" if event == "return" else "step"),
            "call_stack": call_stack_snapshot,
            "call_depth": len(call_stack_snapshot),
            "return_value": _safe_repr(arg) if event == "return" else None,
        }
        if linked_lists:
            # Pick the primary linked list
            primary_ll_key = next(iter(linked_lists))
            payload["linked_list_view"] = linked_lists[primary_ll_key]
        if trees:
            primary_tree_key = next(iter(trees))
            payload["tree_view"] = trees[primary_tree_key]

        sys.__stdout__.write(_TRACE_PREFIX + json.dumps(payload) + "\n")
        sys.__stdout__.flush()

    def __call__(self, frame: types.FrameType, event: str, arg: Any) -> Optional["_PebbleTracer"]:
        if self._steps >= _MAX_TRACE_STEPS:
            return None
        # Only trace the user's file
        if frame.f_code.co_filename != self._filename:
            return self

        if event == "call":
            if frame.f_code.co_name != "<module>":
                self._frame_counter += 1
                frame_id = f"{frame.f_code.co_name}_{self._frame_counter}"
                parent_frame_id = self._active_frames[-1]["frame_id"] if self._active_frames else None
                self._active_frames.append({
                    "frame_id": frame_id,
                    "parent_frame_id": parent_frame_id,
                    "frame": frame,
                })
                self._emit(frame.f_lineno, frame, event, arg)
        elif event == "line":
            self._emit(frame.f_lineno, frame, event, arg)
        elif event == "return":
            self._emit(frame.f_lineno, frame, event, arg)
            if self._active_frames and self._active_frames[-1]["frame"] is frame:
                self._active_frames.pop()
        return self


def run_with_trace(user_code: str, stdin_text: str, user_filename: str) -> None:
    """Execute user_code under a multi-structure DSA live trace in subprocess."""
    import io

    # Redirect stdin so input() calls receive the custom test input
    sys.stdin = io.StringIO(stdin_text)

    # Sanitize sys.path to prevent user code from importing application backend modules
    sys.path = [p for p in sys.path if "backend" not in p.replace("\\", "/").lower()]

    tracer = _PebbleTracer(user_filename)
    sys.settrace(tracer)

    code_obj = compile(user_code, user_filename, "exec")
    global_ns: Dict[str, Any] = {"__name__": "__main__"}
    try:
        exec(code_obj, global_ns)  # noqa: S102
    finally:
        sys.settrace(None)
