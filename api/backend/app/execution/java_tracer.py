"""
Java source code instrumentation and tracing engine for Pebble Playground 2.0 (Universal DSA).

Provides line-by-line runtime tracing for Java algorithms (Bubble Sort, Two Pointers,
Sliding Window, Binary Search, Prefix Sum, HashMaps, Stacks, Queues, Strings)
by instrumenting user Java source code prior to compilation with `javac`.

Emits PEBBLE_TRACE:{"line_number": <N>, "local_vars": {...}} lines that are parsed
by Pebble's unified trace parser in runner.py.
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple


_CLASS_NAME_RE = re.compile(r"\bpublic\s+class\s+([A-Za-z_]\w*)")
_ANY_CLASS_NAME_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
_HAS_MAIN_RE = re.compile(r"\bpublic\s+static\s+void\s+main\s*\(")

# Java primitive, collection, and object types
_TYPE_PATTERN = (
    r"\b(?:int|long|double|float|boolean|char|String|Integer|Double|Boolean|"
    r"Map|HashMap|Set|HashSet|List|ArrayList|Stack|Queue|Deque|ArrayDeque|LinkedList)"
    r"(?:<[^>]+>)?"
    r"(?:\s*\[\s*\])*"
)

# For loop header: `for (int i = 0; ...)` or `for (String s : list)`
_FOR_LOOP_VAR_RE = re.compile(
    r"\bfor\s*\(\s*(?:[A-Za-z_]\w*(?:<[^>]+>)?(?:\s*\[\s*\])*\s+)?([A-Za-z_]\w*)\s*[:=]"
)


# Companion Java class injected alongside instrumented code
PEBBLE_JAVA_TRACER_SOURCE = r"""
class PebbleTracer {
    static int step = 0;
    static final int MAX_STEPS = 500;
    static java.util.List<Frame> callStack = new java.util.ArrayList<>();
    static int frameCounter = 0;

    static class Frame {
        String frameId;
        String parentFrameId;
        String funcName;
        int depth;
        int line;
        String status;
        Object returnValue;
        java.util.Map<String, Object> args = new java.util.LinkedHashMap<>();
        java.util.Map<String, Object> locals = new java.util.LinkedHashMap<>();

        Frame(String frameId, String parentFrameId, String funcName, int depth, int line) {
            this.frameId = frameId;
            this.parentFrameId = parentFrameId;
            this.funcName = funcName;
            this.depth = depth;
            this.line = line;
            this.status = "active";
        }
    }

    public static void pushFrame(String funcName, int line, Object... argPairs) {
        if (step >= MAX_STEPS) return;
        step++;
        String parentId = callStack.isEmpty() ? null : callStack.get(callStack.size() - 1).frameId;
        String frameId = funcName + "_" + (++frameCounter);
        Frame f = new Frame(frameId, parentId, funcName, callStack.size(), line);
        for (int i = 0; i < argPairs.length; i += 2) {
            if (i + 1 < argPairs.length) {
                String k = String.valueOf(argPairs[i]);
                Object v = argPairs[i + 1];
                f.args.put(k, v);
                f.locals.put(k, v);
            }
        }
        callStack.add(f);
        emit(line, "call", f.locals, null);
    }

    public static int popFrame(String funcName, int line, int retVal) {
        popInternal(funcName, line, retVal);
        return retVal;
    }

    public static long popFrame(String funcName, int line, long retVal) {
        popInternal(funcName, line, retVal);
        return retVal;
    }

    public static double popFrame(String funcName, int line, double retVal) {
        popInternal(funcName, line, retVal);
        return retVal;
    }

    public static boolean popFrame(String funcName, int line, boolean retVal) {
        popInternal(funcName, line, retVal);
        return retVal;
    }

    public static String popFrame(String funcName, int line, String retVal) {
        popInternal(funcName, line, retVal);
        return retVal;
    }

    public static <T> T popFrame(String funcName, int line, T retVal) {
        popInternal(funcName, line, retVal);
        return retVal;
    }

    public static void popFrameVoid(String funcName, int line) {
        popInternal(funcName, line, null);
    }

    private static void popInternal(String funcName, int line, Object retVal) {
        if (step >= MAX_STEPS) return;
        step++;
        if (!callStack.isEmpty()) {
            Frame f = callStack.get(callStack.size() - 1);
            f.status = "returning";
            f.returnValue = retVal;
            f.line = line;
            emit(line, "return", f.locals, retVal);
            callStack.remove(callStack.size() - 1);
        } else {
            emit(line, "return", new java.util.HashMap<>(), retVal);
        }
    }

    public static void trace(int line, Object... pairs) {
        if (step >= MAX_STEPS) return;
        step++;
        java.util.Map<String, Object> currentLocals = new java.util.LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) {
            if (i + 1 < pairs.length) {
                currentLocals.put(String.valueOf(pairs[i]), pairs[i + 1]);
            }
        }
        if (!callStack.isEmpty()) {
            Frame top = callStack.get(callStack.size() - 1);
            top.locals.putAll(currentLocals);
            top.line = line;
        }
        emit(line, "line", currentLocals, null);
    }

    private static void emit(int line, String event, java.util.Map<String, Object> locals, Object retVal) {
        StringBuilder sb = new StringBuilder("PEBBLE_TRACE:{\"line_number\":").append(line);
        sb.append(",\"event\":\"").append(event).append("\"");
        if (retVal != null) {
            sb.append(",\"return_value\":").append(formatVal(retVal));
        }
        sb.append(",\"local_vars\":{");
        boolean first = true;
        for (java.util.Map.Entry<String, Object> e : locals.entrySet()) {
            if (!first) sb.append(",");
            first = false;
            sb.append("\"").append(e.getKey()).append("\":").append(formatVal(e.getValue()));
        }
        sb.append("}");

        if (!callStack.isEmpty()) {
            sb.append(",\"call_stack\":[");
            for (int i = 0; i < callStack.size(); i++) {
                if (i > 0) sb.append(",");
                Frame f = callStack.get(i);
                sb.append("{\"func_name\":\"").append(f.funcName).append("\"");
                sb.append(",\"depth\":").append(f.depth);
                sb.append(",\"line_number\":").append(f.line);
                sb.append(",\"frame_id\":\"").append(f.frameId).append("\"");
                if (f.parentFrameId != null) {
                    sb.append(",\"parent_frame_id\":\"").append(f.parentFrameId).append("\"");
                }
                sb.append(",\"status\":\"").append(f.status).append("\"");
                if (f.returnValue != null) {
                    sb.append(",\"return_value\":").append(formatVal(f.returnValue));
                }
                sb.append(",\"args\":{");
                boolean firstArg = true;
                for (java.util.Map.Entry<String, Object> a : f.args.entrySet()) {
                    if (!firstArg) sb.append(",");
                    firstArg = false;
                    sb.append("\"").append(a.getKey()).append("\":").append(formatVal(a.getValue()));
                }
                sb.append("}");
                sb.append(",\"local_vars\":{");
                boolean firstLoc = true;
                for (java.util.Map.Entry<String, Object> l : f.locals.entrySet()) {
                    if (!firstLoc) sb.append(",");
                    firstLoc = false;
                    sb.append("\"").append(l.getKey()).append("\":").append(formatVal(l.getValue()));
                }
                sb.append("}");
                sb.append("}");
            }
            sb.append("]");
        }
        sb.append("}");
        System.out.println(sb.toString());
    }

    private static String formatVal(Object val) {
        if (val == null) return "null";
        if (val instanceof int[]) {
            int[] a = (int[]) val;
            StringBuilder s = new StringBuilder("[");
            for (int i = 0; i < Math.min(a.length, 30); i++) {
                if (i > 0) s.append(",");
                s.append(a[i]);
            }
            return s.append("]").toString();
        }
        if (val instanceof char[]) {
            char[] a = (char[]) val;
            StringBuilder s = new StringBuilder("[");
            for (int i = 0; i < Math.min(a.length, 30); i++) {
                if (i > 0) s.append(",");
                s.append("\"").append(a[i]).append("\"");
            }
            return s.append("]").toString();
        }
        if (val instanceof long[]) {
            long[] a = (long[]) val;
            StringBuilder s = new StringBuilder("[");
            for (int i = 0; i < Math.min(a.length, 30); i++) {
                if (i > 0) s.append(",");
                s.append(a[i]);
            }
            return s.append("]").toString();
        }
        if (val instanceof double[]) return java.util.Arrays.toString((double[]) val);
        if (val instanceof boolean[]) return java.util.Arrays.toString((boolean[]) val);
        if (val instanceof Object[]) return java.util.Arrays.deepToString((Object[]) val);
        if (val instanceof java.util.Map) {
            java.util.Map<?, ?> m = (java.util.Map<?, ?>) val;
            StringBuilder s = new StringBuilder("{");
            boolean first = true;
            int count = 0;
            for (java.util.Map.Entry<?, ?> e : m.entrySet()) {
                if (count++ >= 20) break;
                if (!first) s.append(",");
                first = false;
                s.append("\"").append(String.valueOf(e.getKey())).append("\":").append(formatVal(e.getValue()));
            }
            return s.append("}").toString();
        }
        if (val instanceof java.util.Collection) {
            java.util.Collection<?> c = (java.util.Collection<?>) val;
            StringBuilder s = new StringBuilder("[");
            boolean first = true;
            int count = 0;
            for (Object obj : c) {
                if (count++ >= 30) break;
                if (!first) s.append(",");
                first = false;
                s.append(formatVal(obj));
            }
            return s.append("]").toString();
        }
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
            r"\b(?:int|long|double|float|boolean|char|String|Integer|Double|Boolean|"
            r"Map|HashMap|Set|HashSet|List|ArrayList|Stack|Queue|Deque|ArrayDeque|LinkedList)"
            r"(?:<[^>]+>)?"
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
    """Count block { and } braces, ignoring string literals, character literals, comments, and array literals."""
    clean = re.sub(r"//.*$", "", line)
    clean = re.sub(r'"(?:\\.|[^"\\])*"', '""', clean)
    clean = re.sub(r"'(?:\\.|[^'\\])*'", "''", clean)
    # Ignore array initializer { ... }
    if "=" in clean and "{" in clean and ("}" in clean or clean.strip().endswith(",")):
        clean = re.sub(r"\{[^{}]*\}", "", clean)
    return clean.count("{"), clean.count("}")


_METHOD_DECL_RE = re.compile(
    r"^(?:(?:public|private|protected|static|final|\s)+)?\s*"
    r"([\w<>\[\]]+)\s+"           # return type
    r"([A-Za-z_]\w*)\s*"          # method name
    r"\(([^)]*)\)\s*"             # parameters
    r"(?:throws\s+[\w,\s]+)?\s*\{" # optional throws and {
)


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
    scope_stack: List[Set[str]] = [set()]
    in_method = False
    curr_method: Optional[str] = None
    curr_return_type: Optional[str] = None
    curr_method_depth: int = 0

    for idx, line in enumerate(raw_lines):
        line_num = idx + 1
        stripped = line.strip()

        open_count, close_count = _count_block_braces(line)

        # Check for method declaration
        m_decl = _METHOD_DECL_RE.search(stripped)
        method_params: List[str] = []
        is_user_method = False

        if m_decl and m_decl.group(2) not in ("if", "while", "for", "switch", "catch"):
            ret_type, m_name, params_str = m_decl.groups()
            in_method = True
            curr_method = m_name
            curr_return_type = ret_type.strip()
            curr_method_depth = len(scope_stack) + open_count
            if params_str.strip():
                for param in params_str.split(","):
                    tokens = param.strip().split()
                    if len(tokens) >= 2:
                        p_name = tokens[-1].replace("[", "").replace("]", "").strip()
                        if p_name and p_name not in ("if", "for", "while", "class", "public", "static", "void"):
                            method_params.append(p_name)
            is_user_method = (m_name != "main")

        for _ in range(open_count):
            scope_stack.append(set())

        if method_params and scope_stack:
            for p in method_params:
                scope_stack[-1].add(p)

        new_vars = _extract_declared_vars(line)
        for v in new_vars:
            if scope_stack:
                scope_stack[-1].add(v)

        indent = " " * (len(line) - len(stripped))

        # Handle return statement rewriting for recursion tracking in user methods
        line_to_add = line
        has_return_rewritten = False

        if curr_method and curr_method != "main":
            if stripped.startswith("return "):
                expr = stripped[len("return "):].rstrip(";").strip()
                if curr_return_type != "void":
                    line_to_add = f"{indent}return PebbleTracer.popFrame(\"{curr_method}\", {line_num}, ({expr}));"
                else:
                    line_to_add = f"{indent}{{ PebbleTracer.popFrameVoid(\"{curr_method}\", {line_num}); return; }}"
                has_return_rewritten = True
            elif stripped == "return;":
                line_to_add = f"{indent}{{ PebbleTracer.popFrameVoid(\"{curr_method}\", {line_num}); return; }}"
                has_return_rewritten = True
            elif " return " in stripped and stripped.endswith(";"):
                # Single-line return inside statement, e.g. `if (n <= 1) return 1;`
                ret_idx = stripped.find(" return ")
                prefix = stripped[:ret_idx + len(" return ")]
                expr = stripped[ret_idx + len(" return "):].rstrip(";").strip()
                if curr_return_type != "void":
                    pop_call = f"return PebbleTracer.popFrame(\"{curr_method}\", {line_num}, ({expr}));"
                else:
                    pop_call = f"{{ PebbleTracer.popFrameVoid(\"{curr_method}\", {line_num}); return; }}"

                trace_before = ""
                meaningful_params = [p for p in active_vars if p not in ("args", "in", "scanner", "sc", "br")]
                if meaningful_params:
                    t_args = ", ".join(f'"{p}", {p}' for p in sorted(meaningful_params)[:12])
                    trace_before = f"{indent}PebbleTracer.trace({line_num}, {t_args});\n"

                line_to_add = f"{trace_before}{indent}{prefix[:-len(' return ')]} {pop_call}"
                has_return_rewritten = True

        output_lines.append(line_to_add)

        # If entering a user method, insert pushFrame immediately after the method header
        if is_user_method and curr_method:
            push_indent = " " * (len(line) - len(stripped) + 4)
            push_args = ", ".join(f'"{p}", {p}' for p in method_params)
            output_lines.append(f'{push_indent}PebbleTracer.pushFrame("{curr_method}", {line_num}, {push_args});')

        for _ in range(close_count):
            if len(scope_stack) > 1:
                scope_stack.pop()

        if len(scope_stack) <= 1:
            in_method = False
            curr_method = None

        active_vars = set().union(*scope_stack) if scope_stack else set()

        if not in_method or not stripped:
            continue
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        if stripped.startswith("import ") or stripped.startswith("package "):
            continue
        if stripped.startswith("return ") or stripped == "return;" or has_return_rewritten:
            continue
        if stripped == "break;" or stripped == "continue;" or stripped.startswith("break ") or stripped.startswith("continue "):
            continue
        if (
            stripped.endswith("{")
            and not stripped.startswith("for")
            and not stripped.startswith("while")
            and not stripped.startswith("if")
        ):
            continue

        meaningful_vars = [
            v for v in sorted(active_vars)
            if v not in ("args", "in", "scanner", "sc", "br")
        ]

        if meaningful_vars:
            trace_args = [f'"{v}", {v}' for v in meaningful_vars[:12]]
            args_str = ", ".join(trace_args)

            trace_indent = " " * (len(line) - len(stripped) + 4)
            if stripped.endswith(";"):
                output_lines.append(f"{trace_indent}PebbleTracer.trace({line_num}, {args_str});")
            elif (
                stripped.startswith("for ")
                or stripped.startswith("for(")
                or stripped.startswith("while ")
                or stripped.startswith("while(")
                or stripped.startswith("if ")
                or stripped.startswith("if(")
            ) and stripped.endswith("{"):
                output_lines.append(f"{trace_indent}PebbleTracer.trace({line_num}, {args_str});")

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
