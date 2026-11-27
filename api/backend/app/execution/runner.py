"""
Language dispatcher and Universal DSA trace enrichment engine for Pebble Playground 2.0.

Each executor:
  1. Writes source code to a unique temp file.
  2. Optionally compiles (Java, C++).
  3. Runs in the sandbox subprocess.
  4. Returns an ExecutionResult with enriched Universal DSA trace steps.
  5. Cleans up all temp files.

IMPORTANT: User code is NEVER executed inside the main FastAPI process.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.app.execution.sandbox import run_subprocess
from backend.app.execution.schemas import (
    CallStackFrame,
    ExecutionResult,
    GraphData,
    LinkedListNode,
    TraceStep,
    TreeNode,
)
from backend.app.execution.java_tracer import instrument_java_code

logger = logging.getLogger(__name__)

# Default execution timeouts
_DEFAULT_TIMEOUT = 10  # seconds

# ─── Trace parsing ──────────────────────────────────────────────────────────

_TRACE_PREFIX = "PEBBLE_TRACE:"

# Common pointer variable names in DSA algorithms
_POINTER_CANDIDATES = frozenset(
    {
        "left", "right", "l", "r", "i", "j", "k", "p", "ptr", "index", "idx",
        "low", "high", "mid", "start", "end", "slow", "fast", "curr", "prev",
        "head", "tail", "first", "second", "top", "rear", "front", "pivot",
    }
)


def _detect_data_structure(
    local_vars: Dict[str, Any],
    call_stack: Optional[List[Dict[str, Any]]] = None,
    linked_list_view: Optional[List[Dict[str, Any]]] = None,
    tree_view: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, Optional[str], Optional[Any]]:
    """
    Detect the primary data structure being manipulated in the current step.
    Returns: (ds_type, var_name, var_value)
    """
    if tree_view:
        return "tree", "tree", tree_view
    if linked_list_view:
        return "linked_list", "head", linked_list_view
    if call_stack and len(call_stack) >= 1:
        return "recursion", "call_stack", call_stack

    # Check for Graph (adjacency list/matrix or visited set + queue)
    for k, v in local_vars.items():
        k_lower = k.lower()
        if ("graph" in k_lower or "adj" in k_lower or "edges" in k_lower) and isinstance(v, (dict, list)):
            return "graph", k, v

    # Check for Stack or Queue naming or patterns
    for k, v in local_vars.items():
        k_lower = k.lower()
        if ("stack" in k_lower or k_lower in ("st", "s")) and isinstance(v, list):
            return "stack", k, v
        if ("queue" in k_lower or k_lower in ("q", "deque")) and isinstance(v, list):
            return "queue", k, v

    # Check for HashMaps / Dictionaries / Sets
    for k, v in local_vars.items():
        k_lower = k.lower()
        if isinstance(v, dict):
            return "hashmap", k, v
        if isinstance(v, set) or (isinstance(v, list) and ("seen" in k_lower or "visited" in k_lower or "set" in k_lower)):
            return "set", k, v

    # Check for Strings
    for k, v in local_vars.items():
        k_lower = k.lower()
        if isinstance(v, str) and (k_lower in ("s", "str", "word", "text", "pattern", "input_str") or len(v) >= 2):
            # Only treat as primary string if not just a status word
            if len(v) <= 100:
                return "string", k, v

    # Check for Arrays / Lists
    for k, v in local_vars.items():
        if isinstance(v, list):
            return "array", k, v

    return "primitive", None, None


def _enrich_trace_step(
    line_no: int,
    local_vars: dict,
    prev_vars: dict,
    step_num: int,
    call_stack_raw: Optional[List[dict]] = None,
    linked_list_raw: Optional[List[dict]] = None,
    tree_raw: Optional[List[dict]] = None,
    call_depth_raw: Optional[int] = None,
    event_type_raw: Optional[str] = None,
    return_value_raw: Optional[Any] = None,
) -> TraceStep:
    """
    Extract pointers, windows, changed variables, data structure snapshots,
    and beginner-friendly explanations across all DSA categories.
    """
    changed_vars = [
        k for k, v in local_vars.items()
        if k not in prev_vars or prev_vars[k] != v
    ]

    ds_type, ds_var_name, ds_var_val = _detect_data_structure(
        local_vars, call_stack_raw, linked_list_raw, tree_raw
    )

    # 1. Array & Prefix Sum detection
    active_array = None
    array_len = None
    if ds_type == "array" and ds_var_name:
        active_array = ds_var_name
        array_len = len(ds_var_val) if isinstance(ds_var_val, list) else 0
    else:
        # Fallback to finding list
        for k, v in local_vars.items():
            if isinstance(v, list) and (active_array is None or k.lower() in ("nums", "arr", "a", "data", "array", "list", "prefix")):
                active_array = k
                array_len = len(v)

    # 2. String View
    string_view = None
    if ds_type == "string" and ds_var_name and isinstance(ds_var_val, str):
        string_view = {
            "text": ds_var_val,
            "chars": list(ds_var_val),
            "pointers": {},
            "window": None,
        }
        str_len = len(ds_var_val)
    else:
        str_len = None

    # 3. Detect pointers / indices
    pointers: dict[str, int] = {}
    bound_len = array_len if array_len is not None else (str_len if str_len is not None else None)

    for k, v in local_vars.items():
        if isinstance(v, int) and (k.lower() in _POINTER_CANDIDATES or k.endswith("_idx")):
            if bound_len is not None and -1 <= v <= bound_len + 1:
                pointers[k] = v
            elif bound_len is None and 0 <= v <= 1000:
                pointers[k] = v

    if string_view:
        string_view["pointers"] = pointers

    # 4. Detect active window / range
    window = None
    if "left" in pointers and "right" in pointers and pointers["left"] <= pointers["right"]:
        window = [pointers["left"], pointers["right"]]
    elif "start" in pointers and "end" in pointers and pointers["start"] <= pointers["end"]:
        window = [pointers["start"], pointers["end"]]
    elif "low" in pointers and "high" in pointers and pointers["low"] <= pointers["high"]:
        window = [pointers["low"], pointers["high"]]

    if string_view and window:
        string_view["window"] = window

    # 5. Accessed indices & comparisons
    accessed_indices: list[int] = []
    for p_name, p_val in pointers.items():
        if bound_len is not None and 0 <= p_val < bound_len:
            if p_val not in accessed_indices:
                accessed_indices.append(p_val)

    # Adjacent sorting indices (Bubble Sort, Selection Sort)
    if "j" in pointers and bound_len is not None:
        j_idx = pointers["j"]
        if 0 <= j_idx < bound_len and j_idx not in accessed_indices:
            accessed_indices.append(j_idx)
        if 0 <= j_idx + 1 < bound_len and (j_idx + 1) not in accessed_indices:
            accessed_indices.append(j_idx + 1)

    # 6. HashMap & HashSet snapshot
    hash_map_view = None
    for k, v in local_vars.items():
        if isinstance(v, dict):
            prev_dict = prev_vars.get(k, {}) if isinstance(prev_vars.get(k), dict) else {}
            entries = []
            for entry_k, entry_v in v.items():
                was_updated = entry_k not in prev_dict or prev_dict.get(entry_k) != entry_v
                entries.append({
                    "key": str(entry_k),
                    "value": entry_v,
                    "was_updated": was_updated,
                })
            hash_map_view = {
                "var_name": k,
                "entries": entries,
                "size": len(entries),
            }
            break

    # 7. Stack & Queue snapshots
    stack_view = None
    queue_view = None
    for k, v in local_vars.items():
        k_lower = k.lower()
        if ("stack" in k_lower or k_lower == "st") and isinstance(v, list):
            stack_view = v
            break
        elif ("queue" in k_lower or k_lower in ("q", "deque")) and isinstance(v, list):
            queue_view = v
            break

    # 8. Linked list snapshot
    linked_list_view = None
    if linked_list_raw:
        linked_list_view = [LinkedListNode(**item) for item in linked_list_raw]

    # 9. Tree snapshot
    tree_view = None
    if tree_raw:
        tree_view = [TreeNode(**item) for item in tree_raw]

    # 10. Call stack
    call_stack = None
    if call_stack_raw:
        call_stack = [CallStackFrame(**f) for f in call_stack_raw]

    # 11. Graph snapshot
    graph_view = None
    for k, v in local_vars.items():
        k_lower = k.lower()
        if ("graph" in k_lower or "adj" in k_lower) and isinstance(v, dict):
            nodes = [{"id": str(node), "label": str(node)} for node in v.keys()]
            edges = []
            for src, targets in v.items():
                if isinstance(targets, (list, set)):
                    for tgt in targets:
                        edges.append({"source": str(src), "target": str(tgt)})
            visited_list = []
            for v_key in ("visited", "seen"):
                if v_key in local_vars and isinstance(local_vars[v_key], (list, set, dict)):
                    visited_list = [str(x) for x in local_vars[v_key]]
            curr_node = str(local_vars.get("node", local_vars.get("curr", local_vars.get("u", "")))) or None
            graph_view = GraphData(nodes=nodes, edges=edges, visited=visited_list, current_node=curr_node)
            break

    # 12. Determine operation type
    op_type = "step"
    if event_type_raw in ("call", "return"):
        op_type = event_type_raw
    elif stack_view is not None:
        prev_stack = prev_vars.get("stack", prev_vars.get("st", []))
        if isinstance(prev_stack, list):
            if len(stack_view) > len(prev_stack):
                op_type = "push"
            elif len(stack_view) < len(prev_stack):
                op_type = "pop"
    elif queue_view is not None:
        prev_q = prev_vars.get("queue", prev_vars.get("q", []))
        if isinstance(prev_q, list):
            if len(queue_view) > len(prev_q):
                op_type = "enqueue"
            elif len(queue_view) < len(prev_q):
                op_type = "dequeue"
    elif hash_map_view is not None and any(e["was_updated"] for e in hash_map_view["entries"]):
        op_type = "map_update"
    elif active_array and active_array in changed_vars:
        if prev_vars.get(active_array) and isinstance(prev_vars[active_array], list):
            op_type = "swap" if len(accessed_indices) >= 2 else "update"
        else:
            op_type = "update"
    elif any(k in pointers for k in changed_vars):
        if "right" in changed_vars or "end" in changed_vars or "high" in changed_vars:
            op_type = "expand"
        elif "left" in changed_vars or "start" in changed_vars or "low" in changed_vars:
            op_type = "shrink"
        else:
            op_type = "pointer_move"
    elif len(accessed_indices) >= 2:
        op_type = "compare"

    # 13. Generate beginner-friendly explanation
    explanation_parts = []
    if op_type == "call" and call_stack:
        active_f = call_stack[-1]
        args_str = ", ".join(f"{k} = {v}" for k, v in active_f.args.items())
        if len(call_stack) > 1:
            caller_f = call_stack[-2]
            explanation_parts.append(
                f"{caller_f.func_name} calls {active_f.func_name}({args_str}). "
                f"A new stack frame is created with depth {active_f.depth}."
            )
        else:
            explanation_parts.append(
                f"Calling {active_f.func_name}({args_str}). "
                f"A new stack frame is created with depth {active_f.depth}."
            )
    elif op_type == "return" and call_stack:
        active_f = call_stack[-1]
        ret_val = active_f.return_value if active_f.return_value is not None else return_value_raw
        args_str = ", ".join(f"{k} = {v}" for k, v in active_f.args.items())
        if len(call_stack) == 1:
            explanation_parts.append(
                f"{active_f.func_name}({args_str}) reaches completion and returns {ret_val}."
            )
        elif active_f.depth == 0:
            explanation_parts.append(
                f"{active_f.func_name}({args_str}) reaches the base case and returns {ret_val}."
            )
        else:
            caller_f = call_stack[-2]
            explanation_parts.append(
                f"{active_f.func_name}({args_str}) returns {ret_val} to {caller_f.func_name}."
            )
    elif op_type == "swap" and active_array and len(accessed_indices) >= 2:
        idx_a, idx_b = accessed_indices[0], accessed_indices[1]
        explanation_parts.append(f"Swapped elements at index {idx_a} and {idx_b}")
    elif op_type == "compare" and active_array and len(accessed_indices) >= 2:
        idx_a, idx_b = accessed_indices[0], accessed_indices[1]
        arr_data = local_vars[active_array]
        if idx_a < len(arr_data) and idx_b < len(arr_data):
            explanation_parts.append(f"Comparing {active_array}[{idx_a}] ({arr_data[idx_a]}) with {active_array}[{idx_b}] ({arr_data[idx_b]})")
    elif op_type == "push" and stack_view:
        explanation_parts.append(f"Pushed {stack_view[-1]} onto stack (size: {len(stack_view)})")
    elif op_type == "pop" and stack_view is not None:
        explanation_parts.append(f"Popped top element from stack (size now: {len(stack_view)})")
    elif op_type == "map_update" and hash_map_view:
        updated = [e for e in hash_map_view["entries"] if e["was_updated"]]
        if updated:
            explanation_parts.append(f"Updated map key '{updated[0]['key']}' to {updated[0]['value']}")

    if string_view and ("left" in pointers or "right" in pointers):
        s_chars = string_view["chars"]
        ptrs_desc = []
        for p, idx in pointers.items():
            if 0 <= idx < len(s_chars):
                ptrs_desc.append(f"{p} points to '{s_chars[idx]}' (idx {idx})")
        if ptrs_desc:
            explanation_parts.append(", ".join(ptrs_desc))

    if op_type not in ("call", "return") and changed_vars:
        changes_desc = []
        for k in changed_vars[:3]:
            val = local_vars[k]
            val_str = json.dumps(val) if isinstance(val, (list, dict, str)) else str(val)
            if len(val_str) > 25:
                val_str = val_str[:22] + "..."
            if k in prev_vars:
                prev_val = prev_vars[k]
                prev_str = json.dumps(prev_val) if isinstance(prev_val, (list, dict, str)) else str(prev_val)
                if len(prev_str) > 20:
                    prev_str = prev_str[:17] + "..."
                changes_desc.append(f"{k}: {prev_str} → {val_str}")
            else:
                changes_desc.append(f"{k} = {val_str}")
        explanation_parts.append(", ".join(changes_desc))

    if window:
        explanation_parts.append(f"Window: [{window[0]}..{window[1]}]")

    if explanation_parts:
        explanation = f"Line {line_no}: " + " | ".join(explanation_parts)
    elif call_stack and len(call_stack) >= 1:
        top_frame = call_stack[-1]
        explanation = f"Line {line_no} in {top_frame.func_name} (depth {top_frame.depth}): executing statement."
    elif local_vars:
        explanation = f"Executing line {line_no} with current state: " + ", ".join(f"{k}={v}" for k, v in list(local_vars.items())[:3])
    else:
        explanation = f"Executing line {line_no}"

    # Build brief description for controls/badges
    if op_type == "call" and call_stack:
        active_f = call_stack[-1]
        args_str = ", ".join(f"{k}={v}" for k, v in active_f.args.items())
        desc = f"Call {active_f.func_name}({args_str})"
    elif op_type == "return" and call_stack:
        active_f = call_stack[-1]
        ret_val = active_f.return_value if active_f.return_value is not None else return_value_raw
        desc = f"Return {ret_val} from {active_f.func_name}"
    elif changed_vars:
        desc = f"Line {line_no}: " + ", ".join(f"{k} = {local_vars[k]}" for k in changed_vars[:2])
    else:
        desc = f"Line {line_no}"

    return TraceStep(
        step=step_num,
        line_number=line_no,
        local_vars=local_vars,
        description=desc,
        pointers=pointers,
        active_array=active_array,
        window=window,
        accessed_indices=accessed_indices,
        operation_type=op_type,
        explanation=explanation,
        changed_vars=changed_vars,
        data_structure_type=ds_type,
        string_view=string_view,
        hash_map_view=hash_map_view,
        stack_view=stack_view,
        queue_view=queue_view,
        linked_list_view=linked_list_view,
        tree_view=tree_view,
        call_stack=call_stack,
        call_depth=len(call_stack) if call_stack else (call_depth_raw or 0),
        event_type=event_type_raw or op_type,
        return_value=return_value_raw,
        graph_view=graph_view,
    )


def _parse_trace_lines(raw_stdout: str) -> Tuple[str, List[TraceStep]]:
    """
    Split combined stdout into (user_output, trace_steps).
    Extracts multi-structure snapshots including call stacks, linked lists, and trees.
    Completely removes all PEBBLE_TRACE prefix markers and payloads from user output,
    even when preceded by unbuffered user print statements on the same line.
    """
    user_lines: List[str] = []
    steps: List[TraceStep] = []
    prev_vars: dict = {}

    for line in raw_stdout.splitlines(keepends=True):
        idx = line.find(_TRACE_PREFIX)
        if idx != -1:
            # Any text before the trace prefix is genuine user program output
            user_part = line[:idx]
            if user_part:
                user_lines.append(user_part)

            trace_part = line[idx + len(_TRACE_PREFIX):].strip()
            try:
                data = json.loads(trace_part)
                line_no = data.get("line_number", 0)
                local_vars = data.get("local_vars", {})
                call_stack = data.get("call_stack")
                linked_list_view = data.get("linked_list_view")
                tree_view = data.get("tree_view")
                event_type = data.get("event") or data.get("event_type")
                call_depth = data.get("call_depth")
                return_value = data.get("return_value")

                step_obj = _enrich_trace_step(
                    line_no=line_no,
                    local_vars=local_vars,
                    prev_vars=prev_vars,
                    step_num=len(steps) + 1,
                    call_stack_raw=call_stack,
                    linked_list_raw=linked_list_view,
                    tree_raw=tree_view,
                    call_depth_raw=call_depth,
                    event_type_raw=event_type,
                    return_value_raw=return_value,
                )
                prev_vars = dict(local_vars)
                steps.append(step_obj)
            except Exception:
                # Malformed trace line — treat as user output
                user_lines.append(line[idx:])
        else:
            user_lines.append(line)

    return "".join(user_lines), steps


# ─── Python ─────────────────────────────────────────────────────────────────


def _is_function_only(code: str) -> bool:
    """Check if code consists solely of function/class definitions with no top-level caller."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    has_def = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            has_def = True
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            return False
        else:
            return False
    return has_def


def _build_driver_code(code: str, stdin_text: str) -> str:
    """Given function-only Python code, synthesize a driver that calls the first function."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            func_name = node.name
            params = [p.arg for p in node.args.args if p.arg != "self"]
            return _build_driver_from_params(code, func_name, params, stdin_text)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name != "__init__":
                    func_name = f"{node.name}().{item.name}"
                    params = [p.arg for p in item.args.args if p.arg != "self"]
                    return _build_driver_from_params(code, func_name, params, stdin_text)
            return code

    return code


def _build_driver_from_params(
    code: str, func_name: str, params: list, stdin_text: str
) -> str:
    """Append a driver call to code based on parameter names and stdin."""
    args_from_stdin = []
    if stdin_text.strip():
        for line in stdin_text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                import ast as _ast
                val = _ast.literal_eval(line)
                args_from_stdin.append(repr(val))
            except (ValueError, SyntaxError):
                args_from_stdin.append(repr(line))

    if args_from_stdin and len(args_from_stdin) >= len(params):
        arg_str = ", ".join(args_from_stdin[:len(params)])
    else:
        sample_args = []
        for p in params:
            lower = p.lower()
            if lower in ("nums", "arr", "array", "a", "numbers", "data", "list"):
                sample_args.append("[2, 7, 11, 15]")
            elif lower in ("target", "sum", "k", "val"):
                sample_args.append("9")
            elif lower in ("n", "size", "length", "count"):
                sample_args.append("5")
            elif lower in ("s", "string", "word", "text", "str"):
                sample_args.append('"hello"')
            elif lower in ("matrix", "grid", "board"):
                sample_args.append("[[1,2],[3,4]]")
            elif lower in ("head", "node", "root"):
                sample_args.append("None")
            else:
                sample_args.append("[1, 2, 3, 4, 5]")
        arg_str = ", ".join(sample_args)

    driver = f"\n\n# --- Pebble auto-driver ---\nresult = {func_name}({arg_str})\nif result is not None:\n    print('Result:', result)\n"
    return code + driver


def execute_python(
    code: str,
    stdin_text: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
    enable_trace: bool = True,
) -> ExecutionResult:
    """Execute Python code in an isolated subprocess with live line-by-line tracing."""
    start_time = time.perf_counter()

    if _is_function_only(code):
        code_to_run = _build_driver_code(code, stdin_text)
    else:
        code_to_run = code

    with tempfile.TemporaryDirectory(prefix="pebble_py_") as tmpdir:
        user_script = Path(tmpdir) / "solution.py"
        user_script.write_text(code_to_run, encoding="utf-8")

        if enable_trace:
            tracer_wrapper = Path(tmpdir) / "_tracer_wrapper.py"
            wrapper_code = f"""import sys
from backend.app.execution.tracer import run_with_trace
user_code = open({repr(str(user_script))}, encoding="utf-8").read()
stdin_text = {repr(stdin_text)}
run_with_trace(user_code, stdin_text, {repr(str(user_script))})
"""
            tracer_wrapper.write_text(wrapper_code, encoding="utf-8")

            # Add backend to PYTHONPATH for the wrapper import
            backend_root = str(Path(__file__).resolve().parents[3])
            env = dict(os.environ)
            existing_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                f"{backend_root}{os.pathsep}{existing_pythonpath}"
                if existing_pythonpath
                else backend_root
            )

            cmd = [sys.executable, str(tracer_wrapper)]
        else:
            cmd = [sys.executable, str(user_script)]
            env = None

        proc_stdout, proc_stderr, proc_exit_code, proc_timed_out = run_subprocess(
            cmd=cmd,
            stdin_text=stdin_text if not enable_trace else None,
            timeout_seconds=timeout,
            cwd=tmpdir,
            env=env,
        )

    execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

    if proc_timed_out:
        return ExecutionResult(
            status="timeout",
            stdout="",
            stderr=f"Execution timed out after {timeout} seconds.",
            exit_code=-1,
            execution_time_ms=execution_time_ms,
            timed_out=True,
            language="python",
        )

    if enable_trace:
        clean_stdout, trace_steps = _parse_trace_lines(proc_stdout)
    else:
        clean_stdout = proc_stdout
        trace_steps = []

    if proc_exit_code != 0 and "SyntaxError" in proc_stderr:
        status = "compile_error"
    elif proc_exit_code == 0:
        status = "ok"
    else:
        status = "error"

    return ExecutionResult(
        status=status,
        stdout=clean_stdout,
        stderr=proc_stderr,
        exit_code=proc_exit_code,
        execution_time_ms=execution_time_ms,
        timed_out=False,
        trace_steps=trace_steps,
        trace_available=bool(trace_steps),
        language="python",
    )


# ─── Java ───────────────────────────────────────────────────────────────────


def execute_java(
    code: str,
    stdin_text: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
    enable_trace: bool = True,
) -> ExecutionResult:
    """Execute Java code in an isolated subprocess with source-level trace instrumentation."""
    start_time = time.perf_counter()

    if enable_trace:
        instrumented_code, class_name, is_instrumented = instrument_java_code(code, stdin_text)
    else:
        from backend.app.execution.java_tracer import extract_class_name
        class_name = extract_class_name(code)
        instrumented_code = code
        is_instrumented = False

    with tempfile.TemporaryDirectory(prefix="pebble_java_") as tmpdir:
        src_file = Path(tmpdir) / f"{class_name}.java"
        src_file.write_text(instrumented_code, encoding="utf-8")

        # Compile
        c_stdout, c_stderr, c_exit_code, c_timed_out = run_subprocess(
            cmd=["javac", f"{class_name}.java"],
            timeout_seconds=timeout,
            cwd=tmpdir,
        )

        if c_timed_out:
            return ExecutionResult(
                status="timeout",
                stdout="",
                stderr="Compilation timed out.",
                exit_code=-1,
                execution_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
                timed_out=True,
                language="java",
            )

        if c_exit_code != 0:
            if "is not recognized" in c_stderr or c_exit_code == 127:
                return ExecutionResult(
                    status="unavailable",
                    stdout="",
                    stderr="Java compiler (javac) is not available on this system.",
                    exit_code=c_exit_code,
                    execution_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
                    language="java",
                    language_unavailable=True,
                )

            # If instrumented code failed to compile, fallback to un-instrumented code
            if is_instrumented:
                return execute_java(code, stdin_text=stdin_text, timeout=timeout, enable_trace=False)

            return ExecutionResult(
                status="compile_error",
                stdout="",
                stderr=c_stderr or c_stdout,
                exit_code=c_exit_code,
                execution_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
                language="java",
            )

        # Run
        r_stdout, r_stderr, r_exit_code, r_timed_out = run_subprocess(
            cmd=["java", class_name],
            stdin_text=stdin_text,
            timeout_seconds=timeout,
            cwd=tmpdir,
        )

    execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

    if r_timed_out:
        return ExecutionResult(
            status="timeout",
            stdout="",
            stderr=f"Execution timed out after {timeout} seconds.",
            exit_code=-1,
            execution_time_ms=execution_time_ms,
            timed_out=True,
            language="java",
        )

    if enable_trace:
        clean_stdout, trace_steps = _parse_trace_lines(r_stdout)
    else:
        clean_stdout = r_stdout
        trace_steps = []

    status = "ok" if r_exit_code == 0 else "error"

    return ExecutionResult(
        status=status,
        stdout=clean_stdout,
        stderr=r_stderr,
        exit_code=r_exit_code,
        execution_time_ms=execution_time_ms,
        timed_out=False,
        trace_steps=trace_steps,
        trace_available=bool(trace_steps),
        language="java",
    )


# ─── C++ ────────────────────────────────────────────────────────────────────


def execute_cpp(
    code: str,
    stdin_text: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
) -> ExecutionResult:
    """Execute C++ code in an isolated sandbox subprocess (console output supported)."""
    start_time = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="pebble_cpp_") as tmpdir:
        src_file = Path(tmpdir) / "solution.cpp"
        src_file.write_text(code, encoding="utf-8")
        bin_file = Path(tmpdir) / ("solution.exe" if sys.platform == "win32" else "solution")

        # Compile with g++
        c_stdout, c_stderr, c_exit_code, c_timed_out = run_subprocess(
            cmd=["g++", "-O2", "-std=c++17", str(src_file), "-o", str(bin_file)],
            timeout_seconds=timeout,
            cwd=tmpdir,
        )

        if c_timed_out:
            return ExecutionResult(
                status="timeout",
                stdout="",
                stderr="Compilation timed out.",
                exit_code=-1,
                execution_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
                timed_out=True,
                language="cpp",
            )

        if c_exit_code != 0:
            if "is not recognized" in c_stderr or c_exit_code == 127:
                return ExecutionResult(
                    status="unavailable",
                    stdout="",
                    stderr="C++ compiler (g++) is not available on this system.",
                    exit_code=c_exit_code,
                    execution_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
                    language="cpp",
                    language_unavailable=True,
                )
            return ExecutionResult(
                status="compile_error",
                stdout="",
                stderr=c_stderr or c_stdout,
                exit_code=c_exit_code,
                execution_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
                language="cpp",
            )

        # Run
        r_stdout, r_stderr, r_exit_code, r_timed_out = run_subprocess(
            cmd=[str(bin_file)],
            stdin_text=stdin_text,
            timeout_seconds=timeout,
            cwd=tmpdir,
        )

    execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

    if r_timed_out:
        return ExecutionResult(
            status="timeout",
            stdout="",
            stderr=f"Execution timed out after {timeout} seconds.",
            exit_code=-1,
            execution_time_ms=execution_time_ms,
            timed_out=True,
            language="cpp",
        )

    status = "ok" if r_exit_code == 0 else "error"

    return ExecutionResult(
        status=status,
        stdout=r_stdout,
        stderr=r_stderr,
        exit_code=r_exit_code,
        execution_time_ms=execution_time_ms,
        timed_out=False,
        trace_steps=[],
        trace_available=False,
        language="cpp",
    )


# ─── Dispatcher ─────────────────────────────────────────────────────────────


def execute_code(
    language: str,
    code: str,
    stdin_text: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
    enable_trace: bool = True,
) -> ExecutionResult:
    """Unified entry point for running user code across supported languages."""
    lang = language.lower().strip()
    if lang in ("python", "py"):
        return execute_python(code, stdin_text=stdin_text, timeout=timeout, enable_trace=enable_trace)
    elif lang in ("java",):
        return execute_java(code, stdin_text=stdin_text, timeout=timeout, enable_trace=enable_trace)
    elif lang in ("cpp", "c++"):
        return execute_cpp(code, stdin_text=stdin_text, timeout=timeout)
    else:
        return ExecutionResult(
            status="unavailable",
            stdout="",
            stderr=f"Language '{language}' is not supported. Supported: Python, Java, C++.",
            exit_code=-1,
            execution_time_ms=0.0,
            language=language,
            language_unavailable=True,
        )
