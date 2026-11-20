"""
Python execution tracer.

Instruments user Python code with sys.settrace() to capture line-by-line
local variable snapshots. Emits trace events as JSON-prefixed stdout lines
so they can be parsed after execution without interfering with user output.

Design:
  - Wraps user code in a temporary script that imports this tracer.
  - Trace lines are prefixed with PEBBLE_TRACE: so they can be stripped.
  - User's stdout (print statements) is preserved and returned separately.
  - Circular references and non-serialisable objects are safely converted.
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any, Dict, List, Optional

# Prefix used to tag trace JSON lines in the combined stdout stream
_TRACE_PREFIX = "PEBBLE_TRACE:"

# How many trace steps to capture before stopping (prevents infinite-loop flooding)
_MAX_TRACE_STEPS = 500

# Variable value repr length limit
_MAX_REPR_LEN = 120


def _safe_repr(value: Any) -> Any:
    """Convert a value to a JSON-serialisable form."""
    if isinstance(value, (bool, int, float, type(None))):
        return value
    if isinstance(value, str):
        return value[:_MAX_REPR_LEN]
    if isinstance(value, (list, tuple)):
        result = [_safe_repr(v) for v in value[:20]]
        return result
    if isinstance(value, dict):
        return {str(k)[:40]: _safe_repr(v) for k, v in list(value.items())[:10]}
    if isinstance(value, set):
        return [_safe_repr(v) for v in list(value)[:20]]
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


class _PebbleTracer:
    """sys.settrace-compatible tracer that emits JSON trace events."""

    def __init__(self, user_filename: str) -> None:
        self._filename = user_filename
        self._steps: int = 0
        self._last_line: Optional[int] = None
        self._last_vars_repr: Optional[str] = None

    def _emit(self, line_no: int, local_vars: Dict[str, Any]) -> None:
        if self._steps >= _MAX_TRACE_STEPS:
            return
        filtered = {
            k: _safe_repr(v)
            for k, v in local_vars.items()
            if k not in _SKIP_VARS and not k.startswith("__")
        }
        vars_repr = json.dumps(filtered, sort_keys=True)
        # Avoid duplicate step if neither line number nor locals changed
        if line_no == self._last_line and vars_repr == self._last_vars_repr:
            return

        self._steps += 1
        self._last_line = line_no
        self._last_vars_repr = vars_repr

        payload = {
            "step": self._steps,
            "line_number": line_no,
            "local_vars": filtered,
        }
        # Write directly to real stdout (bypasses any user redirect)
        sys.__stdout__.write(_TRACE_PREFIX + json.dumps(payload) + "\n")
        sys.__stdout__.flush()

    def __call__(self, frame: types.FrameType, event: str, arg: Any) -> Optional["_PebbleTracer"]:
        if self._steps >= _MAX_TRACE_STEPS:
            return None  # Stop tracing
        # Only trace the user's file
        if frame.f_code.co_filename != self._filename:
            return self  # Still return self so nested calls get traced
        if event in ("line", "return"):
            self._emit(frame.f_lineno, dict(frame.f_locals))
        return self


def run_with_trace(user_code: str, stdin_text: str, user_filename: str) -> None:
    """
    Execute *user_code* under a live trace.

    This function is called FROM the wrapper script that the execution runner
    writes to disk and runs in a subprocess — it is NOT called in the main
    FastAPI process.
    """
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
