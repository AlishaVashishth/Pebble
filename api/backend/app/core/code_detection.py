"""Deterministic code detection and extraction for pasted user code snippets."""

import re
from typing import Optional, Tuple

from backend.app.core.dsa_keywords import has_prompt_injection

# Common programming language keywords & syntax patterns
ASSIGNMENT_PATTERN = re.compile(
    r"^\s*(?:let\s+|const\s+|var\s+|[a-zA-Z_]\w*\s*(?::\s*[^=]+)?)=\s*[^=]",
    re.MULTILINE,
)
DEF_OR_CLASS_PATTERN = re.compile(
    r"^\s*(?:def\s+\w+\s*\(|class\s+\w+|function\s+\w*\(|async\s+function\s+\w*\(|"
    r"(?:public|private|protected)?\s*(?:static\s+)?(?:int|void|boolean|bool|string|double|float|long|vector|List|ListNode|TreeNode)\s+\w+\s*\()",
    re.MULTILINE,
)
CONTROL_FLOW_PATTERN = re.compile(
    r"^\s*(?:for\s*\(|for\s+\w+\s+in\b|while\s*\(|while\s+\w+|if\s*\(|if\s+\w+|elif\s+|else\s*:?|return\b)",
    re.MULTILINE,
)
PRINT_OR_IO_PATTERN = re.compile(
    r"(?:print\s*\(|console\.log\s*\(|System\.out\.print|printf\s*\(|std::cout|cout\s*<<)",
)
SLICING_PATTERN = re.compile(r"\[[^\]\n]*::?[^\]\n]*\]")
INCLUDE_OR_IMPORT_PATTERN = re.compile(
    r"^\s*(?:#include\s*<|from\s+\w+\s+import|import\s+\w+|package\s+\w+|using\s+namespace)",
    re.MULTILINE,
)
SEMICOLON_END_PATTERN = re.compile(r";\s*$", re.MULTILINE)
BRACE_LINE_PATTERN = re.compile(r"^\s*[\{\}]\s*$", re.MULTILINE)


def detect_language(code: str) -> str:
    """Heuristically identify the programming language of a code snippet."""
    lower = code.lower()
    if "system.out" in lower or "public class" in lower or "public static void" in lower:
        return "java"
    if "#include" in lower or "std::" in lower or "cout <<" in lower or "vector<" in lower:
        return "cpp"
    if "console.log" in lower or "const " in lower or "let " in lower or "=>" in lower:
        return "javascript"
    if (
        "def " in lower
        or "print(" in lower
        or "import " in lower
        or "::" in code
        or "elif " in lower
        or "#" in code
    ):
        return "python"
    return "python"


def detect_underlying_algorithm(code: str) -> Optional[str]:
    """Detect if snippet uses built-in shortcuts and return the underlying DSA algorithm."""
    # String / array reversal via slicing [::-1], .reverse(), or reversed()
    if re.search(r"\[[^\]]*::\s*-1\s*\]|\.reverse\(\)|reversed\(", code):
        return "String Reversal (Two Pointers: swapping characters from both ends toward the middle)"
    # Built-in sort (.sort(), sorted())
    if re.search(r"\.sort\(\)|sorted\(", code):
        return "Sorting Algorithm (Comparison-based Sorting / Divide and Conquer)"
    return None


def detect_pasted_code(text: str) -> Tuple[bool, Optional[str], Optional[str], str]:
    """Detect and extract fenced or pasted code blocks.

    Returns:
        Tuple[is_code: bool, code: Optional[str], language: Optional[str], remaining_text: str]
    """
    raw = (text or "").strip()
    if not raw or has_prompt_injection(raw):
        return False, None, None, raw

    # 1. Fenced code block (```lang ... ```)
    fenced_match = re.search(r"```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```", raw)
    if fenced_match:
        lang_str = fenced_match.group(1).lower().strip() or None
        code = fenced_match.group(2).strip()
        remaining = (raw[: fenced_match.start()] + " " + raw[fenced_match.end() :]).strip()
        detected_lang = lang_str
        if not detected_lang:
            detected_lang = detect_language(code)
        elif detected_lang in ("py", "python"):
            detected_lang = "python"
        elif detected_lang in ("cpp", "c++"):
            detected_lang = "cpp"
        elif detected_lang in ("js", "javascript"):
            detected_lang = "javascript"
        elif detected_lang == "java":
            detected_lang = "java"
        return True, code, detected_lang, remaining

    # 2. Check for multi-line or single-line code constructs
    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return False, None, None, raw

    # Check for single-line strong code
    single_line_code = False
    if len(lines) == 1:
        line = lines[0]
        if (
            DEF_OR_CLASS_PATTERN.search(line)
            or INCLUDE_OR_IMPORT_PATTERN.search(line)
            or (PRINT_OR_IO_PATTERN.search(line) and ("=" in line or ";" in line or SLICING_PATTERN.search(line)))
            or (ASSIGNMENT_PATTERN.search(line) and SLICING_PATTERN.search(line))
        ):
            single_line_code = True

    # Count code indicators across lines
    code_score = 0
    if DEF_OR_CLASS_PATTERN.search(raw):
        code_score += 3
    if INCLUDE_OR_IMPORT_PATTERN.search(raw):
        code_score += 3
    if PRINT_OR_IO_PATTERN.search(raw):
        code_score += 2
    if SLICING_PATTERN.search(raw):
        code_score += 2
    if CONTROL_FLOW_PATTERN.search(raw):
        code_score += 2
    if len(ASSIGNMENT_PATTERN.findall(raw)) >= 1:
        code_score += 2
    if len(SEMICOLON_END_PATTERN.findall(raw)) >= 1:
        code_score += 2
    if BRACE_LINE_PATTERN.search(raw):
        code_score += 2

    # If code score is high enough or single line code was identified
    is_code = single_line_code or (code_score >= 3 and len(lines) >= 2) or (code_score >= 4)
    if is_code:
        # Separate possible natural language preamble (e.g. "Here is my code:")
        first_line = lines[0].strip()
        is_preamble = (
            not ASSIGNMENT_PATTERN.search(first_line)
            and not DEF_OR_CLASS_PATTERN.search(first_line)
            and not CONTROL_FLOW_PATTERN.search(first_line)
            and not PRINT_OR_IO_PATTERN.search(first_line)
            and not INCLUDE_OR_IMPORT_PATTERN.search(first_line)
            and (first_line.endswith(":") or first_line.endswith("?") or len(first_line.split()) > 3)
            and len(lines) > 1
        )
        if is_preamble:
            remaining_text = first_line
            code_text = "\n".join(lines[1:]).strip()
        else:
            remaining_text = ""
            code_text = raw

        detected_lang = detect_language(code_text)
        return True, code_text, detected_lang, remaining_text

    return False, None, None, raw

