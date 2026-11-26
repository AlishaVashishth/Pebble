"""Programming language normalization and display utilities for Pebble."""

from typing import Optional

_LANGUAGE_ALIASES = {
    "c++": "cpp",
    "cpp": "cpp",
    "cplusplus": "cpp",
    "c": "c",
    "python": "python",
    "py": "python",
    "python3": "python",
    "java": "java",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "rs": "rust",
}

_DISPLAY_NAMES = {
    "cpp": "C++",
    "c": "C",
    "python": "Python",
    "java": "Java",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "go": "Go",
    "rust": "Rust",
}


def normalize_language(language: Optional[str]) -> str:
    """Normalize a programming language name to a canonical lowercase token.
    
    Examples:
        'C++' -> 'cpp'
        'c++' -> 'cpp'
        'Python3' -> 'python'
        'Java' -> 'java'
    """
    if not language:
        return ""
    clean = str(language).strip().lower()
    return _LANGUAGE_ALIASES.get(clean, clean)


def format_language_display(language: Optional[str]) -> str:
    """Format canonical language token for user-facing messages.
    
    Examples:
        'cpp' -> 'C++'
        'python' -> 'Python'
        'java' -> 'Java'
    """
    norm = normalize_language(language)
    return _DISPLAY_NAMES.get(norm, norm.capitalize() if norm else "Unknown")


def languages_match(lang_a: Optional[str], lang_b: Optional[str]) -> bool:
    """Check if two language descriptors refer to the exact same language."""
    norm_a = normalize_language(lang_a)
    norm_b = normalize_language(lang_b)
    return bool(norm_a and norm_b and norm_a == norm_b)
