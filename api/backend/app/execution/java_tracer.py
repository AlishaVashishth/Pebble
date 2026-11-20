"""
Java source code instrumentation and tracing engine for Pebble Playground 2.0.

Provides line-by-line runtime tracing for Java algorithms (Bubble Sort, Two Pointers,
Sliding Window, Binary Search, etc.) by instrumenting user Java source code prior
to compilation with `javac`.

Emits PEBBLE_TRACE:{"line_number": <N>, "local_vars": {...}} lines that are parsed
by Pebble's unified trace parser in runner.py.
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple


_CLASS_NAME_RE = re.compile(r"\bpublic\s+class\s+([A-Za-z_]\w*)")
_ANY_CLASS_NAME_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
_HAS_MAIN_RE = re.compile(r"\bpublic\s+static\s+void\s+main\s*\(")

# Java primitive & common object types
_TYPE_PATTERN = (
    r"\b(?:int|long|double|float|boolean|char|String|Integer|Double|Boolean)"
    r"(?:\s*\[\s*\])*"
)

# For loop header: `for (int i = 0; ...)`
_FOR_LOOP_VAR_RE = re.compile(
    r"\bfor\s*\(\s*(?:int|long|double|float|char)?\s*([A-Za-z_]\w*)\s*[:=]"
)


# Companion Java class injected alongside instrumented code
PEBBLE_JAVA_TRACER_SOURCE = r"""
class PebbleTracer {
    static int step = 0;
    static final int MAX_STEPS = 400;

    public static void trace(int line, Object... pairs) {
        if (step >= MAX_STEPS) return;
        step++;
        StringBuilder sb = new StringBuilder("PEBBLE_TRACE:{\"line_number\":").append(line).append(",\"local_vars\":{");
        boolean first = true;
        for (int i = 0; i < pairs.length; i += 2) {
            if (i + 1 >= pairs.length) break;
            String key = String.valueOf(pairs[i]);
            Object val = pairs[i + 1];
            if (!first) sb.append(",");
            first = false;
            sb.append("\"").append(key).append("\":").append(formatVal(val));
        }
        sb.append("}}");
        System.out.println(sb.toString());
    }

    private static String formatVal(Object val) {
        if (val == null) return "null";
        if (val instanceof int[]) {
            int[] a = (int[]) val;
            StringBuilder s = new StringBuilder("[");
            for (int i = 0; i < a.length; i++) {
                if (i > 0) s.append(",");
                s.append(a[i]);
            }
            return s.append("]").toString();
        }
        if (val instanceof long[]) {
            long[] a = (long[]) val;
            StringBuilder s = new StringBuilder("[");
            for (int i = 0; i < a.length; i++) {
                if (i > 0) s.append(",");
                s.append(a[i]);
            }
            return s.append("]").toString();
        }
        if (val instanceof double[]) return java.util.Arrays.toString((double[]) val);
        if (val instanceof boolean[]) return java.util.Arrays.toString((boolean[]) val);
        if (val instanceof Object[]) return java.util.Arrays.deepToString((Object[]) val);
        if (val instanceof Number || val instanceof Boolean) return String.valueOf(val);
        return "\"" + String.valueOf(val).replace("\"", "\\\"").replace("\n", "\\n") + "\"";
    }
}
"""


def extract_class_name(code: str) -> str:
    """Extract public class name, or first class name, or default to Main."""
    m = _CLASS_NAME_RE.search(code)
    if m:
        return m.group(1)
    m2 = _ANY_CLASS_NAME_RE.search(code)
    if m2:
        return m2.group(1)
    return "Main"


def _extract_declared_vars(line: str) -> List[str]:
    """Extract newly declared variable names from a line of Java code."""
    vars_found: List[str] = []

    # Check for loop variable e.g. for (int i = 0; ...) or for (int x : arr)
    for_match = _FOR_LOOP_VAR_RE.search(line)
    if for_match:
        vars_found.append(for_match.group(1))

    # Strip comments and string literals
    clean = re.sub(r"//.*$", "", line)
    clean = re.sub(r'"(?:\\.|[^"\\])*"', '""', clean).strip()

    if ";" in clean or "=" in clean:
        type_match = re.search(
            r"\b(?:int|long|double|float|boolean|char|String|Integer|Double|Boolean)"
            r"(?:\s*\[\s*\])*\s+([A-Za-z_]\w*)",
            clean,
        )
        if type_match:
            vars_found.append(type_match.group(1))
            # Check for multiple vars on same line: `int a = 1, b = 2;`
            rest = clean[type_match.end() :]
            for m in re.finditer(r",\s*([A-Za-z_]\w*)", rest):
                vars_found.append(m.group(1))

    return [v for v in vars_found if v not in ("if", "for", "while", "return", "class", "public", "static", "void", "true", "false", "null")]


def _count_block_braces(line: str) -> Tuple[int, int]:
    """Count block { and } braces, ignoring string literals, comments, and array literals."""
    clean = re.sub(r"//.*$", "", line)
    clean = re.sub(r'"(?:\\.|[^"\\])*"', '""', clean)
    # Ignore array initializer { ... }
    if "=" in clean and "{" in clean and ("}" in clean or clean.strip().endswith(",")):
        clean = re.sub(r"\{[^{}]*\}", "", clean)
    return clean.count("{"), clean.count("}")


def instrument_java_code(source_code: str, stdin_text: str = "") -> Tuple[str, str, bool]:
    """
    Instrument Java source code with scoped PebbleTracer.trace(...) invocations.

    Returns:
        (instrumented_source, class_name, is_instrumented)
    """
    class_name = extract_class_name(source_code)
    has_main = bool(_HAS_MAIN_RE.search(source_code))

    # If code doesn't define any class, wrap in `public class Main { ... }`
    if not _ANY_CLASS_NAME_RE.search(source_code):
        source_code = f"public class Main {{\n    public static void main(String[] args) {{\n{source_code}\n    }}\n}}"
        class_name = "Main"
        has_main = True

    raw_lines = source_code.splitlines()
    output_lines: List[str] = []

    # Scope stack: each entry is a set of variable names declared at that block depth
    # depth 0: class level
    # depth 1: method level
    # depth >= 2: loop / if blocks
    scope_stack: List[Set[str]] = [set()]
    in_method = False

    for idx, line in enumerate(raw_lines):
        line_num = idx + 1
        stripped = line.strip()

        open_count, close_count = _count_block_braces(line)

        if "public static void main" in line or (
            len(scope_stack) >= 2 and ("(" in line and ")" in line and "{" in line)
        ):
            in_method = True

        # When entering new block(s)
        for _ in range(open_count):
            scope_stack.append(set())

        # Check for newly declared variables on this line
        new_vars = _extract_declared_vars(line)
        for v in new_vars:
            if scope_stack:
                scope_stack[-1].add(v)

        output_lines.append(line)

        # Get the active in-scope variables
        active_vars = set().union(*scope_stack) if scope_stack else set()

        # When closing block(s), pop after
        for _ in range(close_count):
            if len(scope_stack) > 1:
                scope_stack.pop()

        if len(scope_stack) <= 1:
            in_method = False

        # Do not instrument outside methods, comments, imports, package, return
        if not in_method or not stripped:
            continue
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        if stripped.startswith("import ") or stripped.startswith("package "):
            continue
        if stripped.startswith("return ") or stripped == "return;":
            continue
        if (
            stripped.endswith("{")
            and not stripped.startswith("for")
            and not stripped.startswith("while")
            and not stripped.startswith("if")
        ):
            continue

        # Filter down to meaningful DSA variables
        meaningful_vars = [
            v for v in sorted(active_vars)
            if v not in ("args", "in", "scanner", "sc", "br")
        ]

        if meaningful_vars:
            trace_args = [f'"{v}", {v}' for v in meaningful_vars[:12]]
            args_str = ", ".join(trace_args)

            indent = " " * (len(line) - len(stripped) + 4)
            if stripped.endswith(";"):
                output_lines.append(f"{indent}PebbleTracer.trace({line_num}, {args_str});")
            elif (
                stripped.startswith("for ")
                or stripped.startswith("for(")
                or stripped.startswith("while ")
                or stripped.startswith("while(")
                or stripped.startswith("if ")
                or stripped.startswith("if(")
            ) and stripped.endswith("{"):
                output_lines.append(f"{indent}PebbleTracer.trace({line_num}, {args_str});")

    # If class has no main method (e.g. LeetCode Solution class), synthesize a caller
    if not has_main:
        driver = f"""
    public static void main(String[] args) {{
        {class_name} solver = new {class_name}();
        System.out.println("Executing {class_name}...");
    }}
"""
        last_brace_idx = -1
        for i in range(len(output_lines) - 1, -1, -1):
            if "}" in output_lines[i]:
                last_brace_idx = i
                break
        if last_brace_idx != -1:
            output_lines.insert(last_brace_idx, driver)

    # Append PebbleTracer class definition at the bottom
    output_lines.append(PEBBLE_JAVA_TRACER_SOURCE)

    return "\n".join(output_lines), class_name, True
