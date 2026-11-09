"""Auto-generate allowed visual kit API reference from real classes and methods.

Provides dynamic inspection of pebble_kit and pebble_helpers so prompt templates
and validators stay 100% in sync with actual implementation.
"""

from __future__ import annotations

import inspect
from functools import lru_cache

from pebble.templates import pebble_helpers, pebble_kit


def _format_param(p: inspect.Parameter) -> str:
    s = str(p)
    s = s.replace("array([ 0.  , -0.15,  0.  ])", "STAGE")
    s = s.replace("typing.", "")
    return s


@lru_cache(maxsize=1)
def get_allowed_structure_methods() -> dict[str, set[str]]:
    """Return map of structure_name -> set of allowed public method names."""
    classes = [
        pebble_kit.ArrayViz,
        pebble_kit.MapViz,
        pebble_kit.StackViz,
        pebble_kit.QueueViz,
        pebble_kit.LinkedListViz,
        pebble_kit.TreeViz,
        pebble_kit.GraphViz,
        pebble_kit.GridViz,
        pebble_kit.BarsViz,
        pebble_kit.HeapViz,
        pebble_kit.StatePanel,
        pebble_kit.Pointer,
    ]
    methods: dict[str, set[str]] = {}
    for cls in classes:
        name = cls.__name__
        class_methods = {
            m
            for m, f in cls.__dict__.items()
            if not m.startswith("_") and callable(f)
        }
        if hasattr(cls, "intro"):
            class_methods.add("intro")
        methods[name] = class_methods
    return methods


@lru_cache(maxsize=1)
def get_allowed_api_reference() -> str:
    """Generate exact allowed API reference text from the real classes."""
    lines: list[str] = [
        "ALLOWED VISUALIZATION API (call ONLY these methods; no others exist):",
        "CRITICAL RULE: Never call invented methods on visualization structures.",
        "Only the exact methods listed below exist on each class. Every action must use one of these methods.",
        "",
        "SCENE HELPERS (call on self; e.g. self.show_title(...)):",
    ]

    helpers = [
        "show_title",
        "title_card",
        "beat",
        "set_caption",
        "show_legend",
        "step_tag",
        "result_cards",
        "compare_panels",
    ]
    for h in helpers:
        fn = getattr(pebble_kit, h, None) or getattr(pebble_helpers, h, None)
        if fn:
            sig = inspect.signature(fn)
            params = [
                _format_param(p)
                for name, p in sig.parameters.items()
                if name not in ("self", "scene")
            ]
            lines.append(f"  self.{h}({', '.join(params)})")
    lines.append("  finish_scene(self)  # must be the last statement of construct()")
    lines.append("")
    lines.append("STRUCTURES & METHODS (instantiate, then call ONLY the methods listed for that class):")

    classes = [
        pebble_kit.ArrayViz,
        pebble_kit.MapViz,
        pebble_kit.StackViz,
        pebble_kit.QueueViz,
        pebble_kit.LinkedListViz,
        pebble_kit.TreeViz,
        pebble_kit.GraphViz,
        pebble_kit.GridViz,
        pebble_kit.BarsViz,
        pebble_kit.HeapViz,
        pebble_kit.StatePanel,
        pebble_kit.Pointer,
    ]

    for cls in classes:
        sig = inspect.signature(cls.__init__)
        params = [
            _format_param(p)
            for name, p in sig.parameters.items()
            if name not in ("self", "kwargs")
        ]
        lines.append(f"  {cls.__name__}({', '.join(params)})")
        methods = [
            m
            for m, f in cls.__dict__.items()
            if not m.startswith("_") and callable(f)
        ]
        if hasattr(cls, "intro") and "intro" not in methods:
            methods.append("intro")
        for m in sorted(methods):
            fn = getattr(cls, m)
            msig = inspect.signature(fn)
            mparams = [
                _format_param(p)
                for name, p in msig.parameters.items()
                if name not in ("self", "kwargs")
            ]
            lines.append(f"    .{m}({', '.join(mparams)})")
        lines.append("")

    return "\n".join(lines)

