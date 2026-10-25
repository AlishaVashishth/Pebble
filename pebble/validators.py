"""Validate an LLM generation against the pipeline's structural and safety rules.

Returns a list of human-readable problems; an empty list means the generation is
acceptable. The problems are fed back to the LLM on retry.
"""

from __future__ import annotations

import ast
import re

from pebble.environment import EnvInfo
from pebble.models import (
    STATE_MISSING,
    STATE_UNVERIFIED,
    STATE_VERIFIED,
    GenerationResult,
    VideoRequest,
)

SCENE_CLASS_RE = re.compile(r"class\s+(Scene\d+_[A-Za-z0-9_]+)\s*\(Scene\)")

ALLOWED_IMPORTS = {
    "manim",
    "math",
    "itertools",
    "collections",
    "heapq",
    "functools",
    "typing",
    "bisect",
    "copy",
    "dataclasses",
    "numpy",
    "string",
}

FORBIDDEN_NAMES = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "os",
    "sys",
    "subprocess",
    "shutil",
    "socket",
    "requests",
    "urllib",
    "pathlib",
}

LATEX_ONLY_NAMES = {
    "MathTex",
    "Tex",
    "Matrix",
    "IntegerMatrix",
    "DecimalMatrix",
    "DecimalNumber",
    "Integer",
    "Variable",
    "Axes",
    "NumberPlane",
    "NumberLine",
}

FINISH_SCENE = "finish_scene"
HELPERS_MODULE = "pebble_helpers"
BACKGROUND_MARKER = "config.background_color"

ALLOWED_SOLUTION_SOURCES = {"provided", "corrected", "generated"}
REQUIRED_META_FIELDS = ("problem_summary", "solution_source", "programming_language", "complexity", "validation")

_DUNDER_RE = re.compile(r"^__.+__$")


def scene_class_names(manim_code: str) -> list[str]:
    """Scene class names in source order."""
    return [match.group(1) for match in SCENE_CLASS_RE.finditer(manim_code)]


def validate_manim_code(
    manim_code: str, expected_class_names: list[str], latex_available: bool
) -> list[str]:
    """Shape check used by the render repair loop (same rules as generation).

    The repaired script must parse, keep the safety rules and keep exactly the
    same Scene classes in the same order, otherwise the fix is rejected.
    """
    problems: list[str] = []
    if not (manim_code or "").strip():
        return ["manim_code is empty"]

    if "from manim import *" not in manim_code:
        problems.append("manim_code must contain 'from manim import *'")

    try:
        tree = ast.parse(manim_code)
    except SyntaxError as exc:
        problems.append(f"manim_code is not valid Python: {exc.msg} (line {exc.lineno})")
        return problems

    problems.extend(_check_imports(tree))
    problems.extend(_check_names(tree, latex_available))
    problems.extend(_check_finish_scene(tree, list(expected_class_names)))
    problems.extend(_check_background(manim_code))

    found = scene_class_names(manim_code)
    if found != list(expected_class_names):
        problems.append(
            f"scene classes must stay exactly {list(expected_class_names)} in order, got {found}"
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            subclasses_scene = any(
                (isinstance(base, ast.Name) and base.id == "Scene")
                or (isinstance(base, ast.Attribute) and base.attr == "Scene")
                for base in node.bases
            )
            if subclasses_scene and node.name not in expected_class_names:
                problems.append(
                    f"class '{node.name}' subclasses Scene but is not one of the expected scenes"
                )
    return problems


def _import_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name.split(".")[0]
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0]
    return None


def _check_imports(tree: ast.AST) -> list[str]:
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = _import_name(node)
            if name is None:
                continue
            if name not in ALLOWED_IMPORTS:
                where = getattr(node, "lineno", "?")
                problems.append(f"line {where}: import of '{name}' is not allowed")
    return problems


def _check_names(tree: ast.AST, latex_available: bool) -> list[str]:
    problems: list[str] = []
    for node in ast.walk(tree):
        where = getattr(node, "lineno", "?")
        if isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                problems.append(f"line {where}: use of '{node.id}' is not allowed")
            elif node.id == "Code":
                problems.append(
                    f"line {where}: Manim's Code class is not allowed; draw code with Text lines"
                )
            elif not latex_available and node.id in LATEX_ONLY_NAMES:
                problems.append(
                    f"line {where}: '{node.id}' requires LaTeX, which is not available"
                )
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if _DUNDER_RE.match(attr) and attr != "__name__":
                problems.append(f"line {where}: access to dunder attribute '{attr}' is not allowed")
            elif attr in FORBIDDEN_NAMES:
                problems.append(f"line {where}: access to '{attr}' is not allowed")
            elif attr == "Code":
                problems.append(
                    f"line {where}: Manim's Code class is not allowed; draw code with Text lines"
                )
            elif not latex_available and attr in LATEX_ONLY_NAMES:
                problems.append(
                    f"line {where}: '{attr}' requires LaTeX, which is not available"
                )
    return problems


def _check_background(manim_code: str) -> list[str]:
    """A pure black background makes the finished video look empty and unfilmable."""
    if BACKGROUND_MARKER in manim_code:
        return []
    return [
        'set the background once at module level: config.background_color = "#0F172A" '
        "(calm dark navy, never the default pure black)"
    ]


def _is_finish_scene_call(node: ast.AST) -> bool:
    """True for the statement ``finish_scene(self)``."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    func = node.value.func
    if not (isinstance(func, ast.Name) and func.id == FINISH_SCENE):
        return False
    args = node.value.args
    return bool(args) and isinstance(args[0], ast.Name) and args[0].id == "self"


def _chain_has_self_wait(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr == "wait":
            return True
    return False


def _check_finish_scene(tree: ast.AST, class_names: list[str]) -> list[str]:
    """The pipeline owns scene endings: one final ``finish_scene(self)`` call."""
    problems: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == FINISH_SCENE:
                problems.append(
                    f"line {getattr(node, 'lineno', '?')}: {FINISH_SCENE} is provided by the "
                    "pipeline; do not define it"
                )
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and (node.module or "") == HELPERS_MODULE:
                problems.append(
                    f"line {node.lineno}: {FINISH_SCENE} is provided by the pipeline; "
                    "do not import it"
                )
            for alias in node.names:
                if alias.name.split(".")[-1] == FINISH_SCENE or alias.name == HELPERS_MODULE:
                    problems.append(
                        f"line {node.lineno}: {FINISH_SCENE} is provided by the pipeline; "
                        "do not import it"
                    )
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == FINISH_SCENE:
                    problems.append(
                        f"line {node.lineno}: do not assign to {FINISH_SCENE}; it is provided "
                        "by the pipeline"
                    )
        elif isinstance(node, ast.While) and _chain_has_self_wait(node):
            problems.append(
                f"line {node.lineno}: a while loop around self.wait is not allowed; "
                f"end the scene with {FINISH_SCENE}(self) instead"
            )

    classes = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    for name in class_names:
        class_node = classes.get(name)
        if class_node is None:
            continue
        construct = next(
            (
                item
                for item in class_node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == "construct"
            ),
            None,
        )
        if construct is None:
            problems.append(f"scene {name} has no construct method")
            continue
        last = construct.body[-1] if construct.body else None
        if last is None or not _is_finish_scene_call(last):
            problems.append(
                f"scene {name}: the last statement of construct must be exactly "
                f"{FINISH_SCENE}(self) (do not write your own FadeOut)"
            )
    return problems


def _check_structure(manim_code: str, tree: ast.AST, result: GenerationResult) -> list[str]:
    problems: list[str] = []
    scenes = result.meta.scenes

    matched_names = [m.group(1) for m in SCENE_CLASS_RE.finditer(manim_code)]
    if not matched_names:
        problems.append("no scene class matching 'Scene{N}_{Name}(Scene)' was found")

    numbers: list[int] = []
    for name in matched_names:
        match = re.match(r"Scene(\d+)_", name)
        numbers.append(int(match.group(1)) if match else -1)
    expected = list(range(1, len(matched_names) + 1))
    if numbers != expected:
        problems.append(
            f"scene numbering must be exactly {expected} in order, got {numbers}"
        )

    if len(matched_names) != len(scenes):
        problems.append(
            f"scene count mismatch: script has {len(matched_names)} scene class(es) "
            f"but meta lists {len(scenes)}"
        )
    else:
        for index, (class_name, scene) in enumerate(zip(matched_names, scenes), start=1):
            if scene.class_name != class_name:
                problems.append(
                    f"scene {index}: meta class_name '{scene.class_name}' does not match "
                    f"script class '{class_name}'"
                )
            if not scene.narration.strip():
                problems.append(f"scene {index} ({class_name}): narration is empty")

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            subclasses_scene = any(
                (isinstance(base, ast.Name) and base.id == "Scene")
                or (isinstance(base, ast.Attribute) and base.attr == "Scene")
                for base in node.bases
            )
            if subclasses_scene and node.name not in matched_names:
                problems.append(
                    f"class '{node.name}' subclasses Scene but does not follow the "
                    "Scene{{N}}_{{Name}} naming rule"
                )

    problems.extend(_check_finish_scene(tree, matched_names))
    return problems


def _check_meta(result: GenerationResult) -> list[str]:
    problems: list[str] = []
    meta = result.meta
    for field in REQUIRED_META_FIELDS:
        if not meta.field_present(field):
            problems.append(f"meta field '{field}' is missing")
    if not meta.problem_summary.strip():
        problems.append("meta field 'problem_summary' must not be empty")
    if meta.field_present("solution_source") and meta.solution_source not in ALLOWED_SOLUTION_SOURCES:
        problems.append(
            f"meta solution_source must be one of {sorted(ALLOWED_SOLUTION_SOURCES)}, "
            f"got '{meta.solution_source}'"
        )
    if not meta.programming_language.strip():
        problems.append("meta field 'programming_language' must not be empty")
    if not meta.nested_field_present("complexity", "time") or not meta.complexity.time.strip():
        problems.append("meta field 'complexity.time' is missing or empty")
    if not meta.nested_field_present("complexity", "space") or not meta.complexity.space.strip():
        problems.append("meta field 'complexity.space' is missing or empty")
    if not meta.nested_field_present("validation", "performed"):
        problems.append("meta field 'validation.performed' is missing")
    return problems


def _check_solution_state(
    result: GenerationResult, request: VideoRequest
) -> list[str]:
    problems: list[str] = []
    state = request.solution_state
    source = result.meta.solution_source

    if state == STATE_MISSING and source != "generated":
        problems.append(
            f"solution_state is 'missing' so solution_source must be 'generated', got '{source}'"
        )
    elif state == STATE_VERIFIED and source != "provided":
        problems.append(
            f"solution_state is 'verified' so solution_source must be 'provided', got '{source}'"
        )
    elif state == STATE_UNVERIFIED:
        if source not in {"provided", "corrected"}:
            problems.append(
                f"solution_state is 'unverified' so solution_source must be 'provided' or "
                f"'corrected', got '{source}'"
            )
        if result.meta.validation.performed is not True:
            problems.append(
                "solution_state is 'unverified' so validation.performed must be true"
            )
    return problems


def validate_generation(
    result: GenerationResult, request: VideoRequest, env_info: EnvInfo
) -> list[str]:
    problems: list[str] = []

    manim_code = result.manim_code or ""
    if not manim_code.strip():
        problems.append("manim_code is empty")
        return problems

    if "from manim import *" not in manim_code:
        problems.append("manim_code must start with 'from manim import *'")

    tree: ast.AST | None = None
    try:
        tree = ast.parse(manim_code)
    except SyntaxError as exc:
        problems.append(f"manim_code is not valid Python: {exc.msg} (line {exc.lineno})")

    if tree is not None:
        problems.extend(_check_imports(tree))
        problems.extend(_check_names(tree, env_info.latex_available))
        problems.extend(_check_structure(manim_code, tree, result))
        problems.extend(_check_background(manim_code))

    problems.extend(_check_meta(result))
    problems.extend(_check_solution_state(result, request))

    if not (result.solution_code or "").strip():
        problems.append("solution_code is empty")

    return problems
