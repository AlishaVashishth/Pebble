"""
Language dispatcher for the Pebble code execution engine.

Each executor:
  1. Writes source code to a unique temp file.
  2. Optionally compiles (Java, C++).
  3. Runs in the sandbox subprocess.
  4. Returns an ExecutionResult.
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
from typing import List, Optional

from backend.app.execution.sandbox import run_subprocess
from backend.app.execution.schemas import ExecutionResult, TraceStep
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
        "head", "tail", "first", "second",
    }
)


def _enrich_trace_step(
    line_no: int,
    local_vars: dict,
    prev_vars: dict,
    step_num: int,
) -> TraceStep:
    """Extract pointers, windows, changed variables, and beginner-friendly explanations."""
    changed_vars = [
        k for k, v in local_vars.items()
        if k not in prev_vars or prev_vars[k] != v
    ]

    # Find the primary array/list
    active_array = None
    array_len = None
    for k, v in local_vars.items():
        if isinstance(v, list):
            # Prioritize standard names like nums, arr, a
            if active_array is None or k.lower() in ("nums", "arr", "a", "data", "array", "list"):
                active_array = k
                array_len = len(v)

    # Detect pointers/indices (integers within or near array bounds)
    pointers: dict[str, int] = {}
    for k, v in local_vars.items():
        if isinstance(v, int) and (k.lower() in _POINTER_CANDIDATES or k.endswith("_idx")):
            if array_len is not None and -1 <= v <= array_len + 1:
                pointers[k] = v
            elif array_len is None and 0 <= v <= 1000:
                pointers[k] = v

    # Detect active window/range
    window = None
    if "left" in pointers and "right" in pointers and pointers["left"] <= pointers["right"]:
        window = [pointers["left"], pointers["right"]]
    elif "start" in pointers and "end" in pointers and pointers["start"] <= pointers["end"]:
        window = [pointers["start"], pointers["end"]]
    elif "low" in pointers and "high" in pointers and pointers["low"] <= pointers["high"]:
        window = [pointers["low"], pointers["high"]]

    # Identify accessed indices & comparisons
    accessed_indices: list[int] = []
    for p_name, p_val in pointers.items():
        if array_len is not None and 0 <= p_val < array_len:
            if p_val not in accessed_indices:
                accessed_indices.append(p_val)

    # In adjacent comparison / sorting algorithms (e.g. Bubble Sort with pointer j)
    if "j" in pointers and array_len is not None:
        j_idx = pointers["j"]
        if 0 <= j_idx < array_len and j_idx not in accessed_indices:
            accessed_indices.append(j_idx)
        if 0 <= j_idx + 1 < array_len and (j_idx + 1) not in accessed_indices:
            accessed_indices.append(j_idx + 1)

    # Determine operation category
    op_type = "step"
    if active_array and active_array in changed_vars:
        # Check if this was a swap (array values permuted)
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

    # Generate plain-English explanation
    explanation_parts = []

    # Algorithm-specific explanation enrichments
    if op_type == "swap" and active_array and len(accessed_indices) >= 2:
        idx_a, idx_b = accessed_indices[0], accessed_indices[1]
        explanation_parts.append(f"Swapped elements at index {idx_a} and {idx_b}")
    elif op_type == "compare" and active_array and len(accessed_indices) >= 2:
        idx_a, idx_b = accessed_indices[0], accessed_indices[1]
        arr_data = local_vars[active_array]
        if idx_a < len(arr_data) and idx_b < len(arr_data):
            explanation_parts.append(f"Comparing {active_array}[{idx_a}] ({arr_data[idx_a]}) with {active_array}[{idx_b}] ({arr_data[idx_b]})")

    if changed_vars:
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
        explanation = "Line " + str(line_no) + ": " + " | ".join(explanation_parts)
    elif local_vars:
        explanation = f"Executing line {line_no} with current state: " + ", ".join(f"{k}={v}" for k, v in list(local_vars.items())[:3])
    else:
        explanation = f"Executing line {line_no}"

    # Build brief description for controls/badges
    if changed_vars:
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
    )


def _parse_trace_lines(raw_stdout: str):
    """
    Split combined stdout into (user_output, trace_steps).

    Lines prefixed with PEBBLE_TRACE: are trace events; all other lines
    are the user's actual stdout.
    """
    import json

    user_lines: List[str] = []
    steps: List[TraceStep] = []
    prev_vars: dict = {}

    for line in raw_stdout.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if stripped.startswith(_TRACE_PREFIX):
            try:
                data = json.loads(stripped[len(_TRACE_PREFIX):])
                line_no = data.get("line_number", 0)
                local_vars = data.get("local_vars", {})

                step_obj = _enrich_trace_step(
                    line_no=line_no,
                    local_vars=local_vars,
                    prev_vars=prev_vars,
                    step_num=len(steps) + 1,
                )
                prev_vars = dict(local_vars)
                steps.append(step_obj)
            except Exception:
                # Malformed trace line — treat as user output
                user_lines.append(line)
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
        elif isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            continue  # imports are fine
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            # Top-level assignments like `result = func(...)` are callers
            return False
        else:
            # Any other top-level statement (Expr, For, While, If, Print, etc.)
            return False
    return has_def


def _build_driver_code(code: str, stdin_text: str) -> str:
    """Given function-only Python code, synthesize a driver that calls the first function.

    Uses stdin_text to parse arguments. If stdin_text is empty, uses the function's
    default arguments or sample data based on parameter names.
    """
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    # Find the first user-defined function
    func_node = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            func_node = node
            break
        elif isinstance(node, ast.ClassDef):
            # Look for a method inside the class (like Solution.twoSum)
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name != "__init__":
                    # For class methods, we'd need to instantiate
                    func_name = f"{node.name}().{item.name}"
                    params = [p.arg for p in item.args.args if p.arg != "self"]
                    return _build_driver_from_params(code, func_name, params, stdin_text)
            return code

    if not func_node:
        return code

    func_name = func_node.name
    params = [p.arg for p in func_node.args.args if p.arg != "self"]
    return _build_driver_from_params(code, func_name, params, stdin_text)


def _build_driver_from_params(
    code: str, func_name: str, params: list, stdin_text: str
) -> str:
    """Append a driver call to code based on parameter names and stdin."""
    # Try to parse arguments from stdin
    args_from_stdin = []
    if stdin_text.strip():
        for line in stdin_text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # Try to evaluate as a Python literal (list, number, string)
            try:
                import ast as _ast
                val = _ast.literal_eval(line)
                args_from_stdin.append(repr(val))
            except (ValueError, SyntaxError):
                # Treat as a raw string
                args_from_stdin.append(repr(line))

    if args_from_stdin and len(args_from_stdin) >= len(params):
        # Use stdin-provided arguments
        arg_str = ", ".join(args_from_stdin[:len(params)])
    else:
        # Generate sample arguments based on parameter names
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
) -> ExecutionResult:
    """Execute Python code with sys.settrace instrumentation."""
    # Auto-detect function-only code and append a driver call
    effective_code = code
    if _is_function_only(code):
        effective_code = _build_driver_code(code, stdin_text)
        logger.info("Auto-driver appended for function-only code")

    # Determine the Python executable for the venv (same interpreter as us)
    python_exe = sys.executable

    # Build the wrapper script path (the tracer module lives next to this file)
    tracer_module_path = Path(__file__).parent / "tracer.py"

    with tempfile.TemporaryDirectory(prefix="pebble_py_") as tmp_dir:
        # Write user code (or auto-driver augmented code) to file
        user_file = os.path.join(tmp_dir, "user_code.py")
        with open(user_file, "w", encoding="utf-8") as f:
            f.write(effective_code)

        # Write wrapper script that imports tracer and runs user code
        wrapper_file = os.path.join(tmp_dir, "wrapper.py")
        # Inject the tracer module path into the wrapper's sys.path
        wrapper_code = f"""\
import sys
sys.path.insert(0, {repr(str(tracer_module_path.parent.parent.parent.parent))})

import os, io

# Read user code and stdin from env vars written by runner
_user_file = {repr(user_file)}
_stdin_text = {repr(stdin_text)}

with open(_user_file, "r", encoding="utf-8") as _f:
    _user_code = _f.read()

from backend.app.execution.tracer import run_with_trace
run_with_trace(_user_code, _stdin_text, _user_file)
"""
        with open(wrapper_file, "w", encoding="utf-8") as f:
            f.write(wrapper_code)

        start = time.perf_counter()
        try:
            stdout, stderr, exit_code, timed_out = run_subprocess(
                cmd=[python_exe, wrapper_file],
                stdin_text=stdin_text,
                timeout_seconds=timeout,
                cwd=tmp_dir,
            )
        except FileNotFoundError:
            return ExecutionResult(
                status="unavailable",
                stderr="Python interpreter not found.",
                language="python",
                language_unavailable=True,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000

        if timed_out:
            return ExecutionResult(
                status="timeout",
                stdout=stdout,
                stderr=f"Execution timed out after {timeout} seconds.",
                exit_code=-1,
                execution_time_ms=elapsed_ms,
                timed_out=True,
                language="python",
            )

        # Parse trace from combined stdout
        user_stdout, trace_steps = _parse_trace_lines(stdout)

        # Classify error type
        status = "ok"
        if exit_code != 0:
            if "SyntaxError" in stderr or "IndentationError" in stderr or "TabError" in stderr:
                status = "compile_error"
            else:
                status = "error"

        return ExecutionResult(
            status=status,
            stdout=user_stdout,
            stderr=stderr,
            exit_code=exit_code,
            execution_time_ms=elapsed_ms,
            trace_steps=trace_steps,
            trace_available=len(trace_steps) > 0,
            language="python",
        )


# ─── Java ───────────────────────────────────────────────────────────────────

_CLASS_RE = re.compile(r"\bpublic\s+class\s+(\w+)")


def _extract_java_class_name(code: str) -> str:
    """Extract the public class name from Java source (needed for filename)."""
    m = _CLASS_RE.search(code)
    return m.group(1) if m else "Main"


def execute_java(
    code: str,
    stdin_text: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
) -> ExecutionResult:
    """Compile and execute Java code with automated runtime instrumentation."""
    class_name = _extract_java_class_name(code)

    # Attempt to instrument the Java code with PebbleTracer calls
    instrumented_code = None
    try:
        instrumented_code, detected_class, is_inst = instrument_java_code(code, stdin_text)
        if is_inst:
            class_name = detected_class
    except Exception as exc:
        logger.warning("Java instrumentation failed: %s, falling back to original code", exc)

    with tempfile.TemporaryDirectory(prefix="pebble_java_") as tmp_dir:
        # Determine source code to try (instrumented first, fallback to original)
        use_instrumented = bool(instrumented_code)
        source_file = os.path.join(tmp_dir, f"{class_name}.java")
        with open(source_file, "w", encoding="utf-8") as f:
            f.write(instrumented_code if use_instrumented else code)

        # Compile
        compile_start = time.perf_counter()
        try:
            stdout_c, stderr_c, exit_c, timed_out_c = run_subprocess(
                cmd=["javac", source_file],
                timeout_seconds=30,  # compilation can take longer
                cwd=tmp_dir,
            )
        except FileNotFoundError:
            return ExecutionResult(
                status="unavailable",
                stderr="Java compiler (javac) not found. Please install a JDK.",
                language="java",
                language_unavailable=True,
            )

        # If instrumented compilation failed, fall back to compiling the original code
        if exit_c != 0 and use_instrumented:
            logger.info("Instrumented Java compilation failed, falling back to original code: %s", stderr_c)
            with open(source_file, "w", encoding="utf-8") as f:
                f.write(code)
            stdout_c, stderr_c, exit_c, timed_out_c = run_subprocess(
                cmd=["javac", source_file],
                timeout_seconds=30,
                cwd=tmp_dir,
            )
            use_instrumented = False

        if exit_c != 0:
            return ExecutionResult(
                status="compile_error",
                stderr=stderr_c or stdout_c,
                exit_code=exit_c,
                execution_time_ms=(time.perf_counter() - compile_start) * 1000,
                language="java",
            )

        # Run
        run_start = time.perf_counter()
        try:
            stdout_r, stderr_r, exit_r, timed_out_r = run_subprocess(
                cmd=["java", "-cp", tmp_dir, class_name],
                stdin_text=stdin_text,
                timeout_seconds=timeout,
                cwd=tmp_dir,
            )
        except FileNotFoundError:
            return ExecutionResult(
                status="unavailable",
                stderr="Java runtime (java) not found. Please install a JRE/JDK.",
                language="java",
                language_unavailable=True,
            )

        elapsed_ms = (time.perf_counter() - run_start) * 1000

        if timed_out_r:
            return ExecutionResult(
                status="timeout",
                stdout=stdout_r,
                stderr=f"Execution timed out after {timeout} seconds.",
                exit_code=-1,
                execution_time_ms=elapsed_ms,
                timed_out=True,
                language="java",
            )

        # Parse trace lines if instrumentation was active
        user_stdout, trace_steps = _parse_trace_lines(stdout_r)
        status = "ok" if exit_r == 0 else "error"
        return ExecutionResult(
            status=status,
            stdout=user_stdout,
            stderr=stderr_r,
            exit_code=exit_r,
            execution_time_ms=elapsed_ms,
            trace_steps=trace_steps,
            trace_available=len(trace_steps) > 0,
            language="java",
        )


# ─── C++ ────────────────────────────────────────────────────────────────────


def execute_cpp(
    code: str,
    stdin_text: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
) -> ExecutionResult:
    """Compile and execute C++ code using g++."""
    with tempfile.TemporaryDirectory(prefix="pebble_cpp_") as tmp_dir:
        source_file = os.path.join(tmp_dir, "solution.cpp")
        binary_file = os.path.join(tmp_dir, "solution.exe" if os.name == "nt" else "solution")

        with open(source_file, "w", encoding="utf-8") as f:
            f.write(code)

        # Compile
        compile_start = time.perf_counter()
        try:
            stdout_c, stderr_c, exit_c, _ = run_subprocess(
                cmd=["g++", "-O0", "-std=c++17", "-o", binary_file, source_file],
                timeout_seconds=30,
                cwd=tmp_dir,
            )
        except FileNotFoundError:
            return ExecutionResult(
                status="unavailable",
                stderr="C++ compiler (g++) not found. Please install GCC/MinGW.",
                language="cpp",
                language_unavailable=True,
            )

        if exit_c != 0:
            return ExecutionResult(
                status="compile_error",
                stderr=stderr_c or stdout_c,
                exit_code=exit_c,
                execution_time_ms=(time.perf_counter() - compile_start) * 1000,
                language="cpp",
            )

        # Run
        run_start = time.perf_counter()
        try:
            stdout_r, stderr_r, exit_r, timed_out_r = run_subprocess(
                cmd=[binary_file],
                stdin_text=stdin_text,
                timeout_seconds=timeout,
                cwd=tmp_dir,
            )
        except FileNotFoundError:
            return ExecutionResult(
                status="unavailable",
                stderr="Compiled binary not found (compilation may have silently failed).",
                language="cpp",
                language_unavailable=True,
            )

        elapsed_ms = (time.perf_counter() - run_start) * 1000

        if timed_out_r:
            return ExecutionResult(
                status="timeout",
                stdout=stdout_r,
                stderr=f"Execution timed out after {timeout} seconds.",
                exit_code=-1,
                execution_time_ms=elapsed_ms,
                timed_out=True,
                language="cpp",
            )

        status = "ok" if exit_r == 0 else "error"
        return ExecutionResult(
            status=status,
            stdout=stdout_r,
            stderr=stderr_r,
            exit_code=exit_r,
            execution_time_ms=elapsed_ms,
            trace_available=False,
            language="cpp",
        )


# ─── Dispatcher ─────────────────────────────────────────────────────────────


def execute_code(
    language: str,
    code: str,
    stdin_text: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
) -> ExecutionResult:
    """Route to the appropriate language executor."""
    lang = language.lower().strip()
    if lang == "python":
        return execute_python(code, stdin_text, timeout)
    elif lang == "java":
        return execute_java(code, stdin_text, timeout)
    elif lang in ("cpp", "c++"):
        return execute_cpp(code, stdin_text, timeout)
    else:
        return ExecutionResult(
            status="unavailable",
            stderr=f"Language '{language}' is not supported. Supported: Python, Java, C++.",
            language=language,
            language_unavailable=True,
        )
