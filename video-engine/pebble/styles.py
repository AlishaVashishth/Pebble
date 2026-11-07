"""Explanation styles shared by the prompt builder and the CLI."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BEGINNER_FRIENDLY = "beginner_friendly"

STYLES: dict[str, str] = {
    "beginner_friendly": (
        "Explain to a curious 5-year-old who has never coded. Warm, patient, everyday "
        "words, one idea per sentence, one real-life picture per problem that you come "
        "back to. Keep every stage of the teaching order (hook, understand the problem, "
        "brute force and why it is slow, the aha, the smart trace, the recap) and give "
        "each stage a little more room than the other styles. Use 9-13 scenes, about "
        "3-5 minutes total."
    ),
    "interview_focused": (
        "Assume the viewer is preparing for coding interviews. Keep every stage of the "
        "teaching order, but state the brute force and why it is slow quickly, then give "
        "the optimal idea, trace it once on the same example, call out edge cases and end "
        "with time/space trade-offs and what to say in an interview. Use 8-11 scenes, "
        "about 3-4 minutes total."
    ),
    "detailed": (
        "Deep dive: intuition, why it is correct, two examples including an edge case, a "
        "step-by-step walkthrough of every stage, a complexity derivation and common "
        "mistakes. Keep the same teaching order and never skip the brute force. Use 10-13 "
        "scenes, about 5-7 minutes total."
    ),
    "concise": (
        "Quick recap for someone who knows the basics: shorten every stage of the teaching "
        "order but never remove one - the problem in a sentence, the brute force and why it "
        "is slow, the key idea, one fast trace, the complexity. Use 9 scenes, about 2 "
        "minutes total."
    ),
}

DEFAULT_STYLE = BEGINNER_FRIENDLY


def supported_styles() -> list[str]:
    """Canonical style names, in the order they are documented."""
    return list(STYLES)


def is_supported_style(name: str | None) -> bool:
    """True when the style is one of the known styles (case-insensitive)."""
    return (name or "").strip().lower() in STYLES


def get_style(name: str | None) -> tuple[str, str]:
    """Return (canonical_name, style_text); unknown names fall back with a warning."""
    key = (name or "").strip().lower()
    if key in STYLES:
        return key, STYLES[key]
    logger.warning(
        "Unknown explanation style %r; falling back to %r", name, DEFAULT_STYLE
    )
    return DEFAULT_STYLE, STYLES[DEFAULT_STYLE]
