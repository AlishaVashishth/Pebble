"""Deterministic caption normalizer.

Enforces the strict 70-character limit on set_caption calls without needing an LLM call.
"""

from __future__ import annotations

import ast
import re


def normalize_caption_text(text: str, max_len: int = 70) -> str:
    """Normalize and clamp caption text to at most max_len characters at word boundary."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned

    cutoff = max_len - 3
    truncated = cleaned[:cutoff]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated + "..."


def normalize_captions(code: str, max_len: int = 70) -> str:
    """Clamp caption text passed to set_caption or beat calls at word boundaries."""
    if "set_caption" not in code and "beat" not in code:
        return code

    try:
        tree = ast.parse(code)
    except Exception:
        # Fallback to regex if code is not syntactically complete yet
        def _repl(m: re.Match[str]) -> str:
            prefix, quote, content, suffix = m.group(1), m.group(2), m.group(3), m.group(4)
            norm = normalize_caption_text(content, max_len)
            return f"{prefix}{quote}{norm}{quote}{suffix}"

        pattern = re.compile(
            r'((?:set_caption|beat)\s*\(\s*)([\'"])(.*?)\2(\s*[,)])', re.S
        )
        return pattern.sub(_repl, code)

    replacements: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in {"set_caption", "beat"}:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        val = node.args[0].value
        if not isinstance(val, str):
            continue
        if len(" ".join(val.split())) > max_len:
            norm = normalize_caption_text(val, max_len)
            replacements.append((val, norm))

    result = code
    for old_val, new_val in replacements:
        # Replace occurrences inside set_caption calls
        result = result.replace(f'"{old_val}"', f'"{new_val}"')
        result = result.replace(f"'{old_val}'", f"'{new_val}'")

    return result

