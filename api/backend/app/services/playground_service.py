"""
Playground service — Phase 1.

Handles two modes:
  • explain  — user pastes code; we find or generate an explanation
  • solve    — user describes a problem; we search DB first, then generate

Reuses:
  • ProblemService / SolutionRepository for DB lookups (no duplication)
  • get_llm_provider() / LLMProvider.complete() for generation
  • No video-generation code is touched.
"""

import logging
import re
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.core.code_detection import detect_underlying_algorithm
from backend.app.core.dsa_keywords import contains_dsa_keyword, has_prompt_injection
from backend.app.integrations.llm import get_llm_provider
from backend.app.repositories.solution_repository import SolutionRepository
from backend.app.schemas.playground import PlaygroundRequest, PlaygroundResponse
from backend.app.services.problem_service import ProblemService

logger = logging.getLogger(__name__)

# ─── Scope Validation Patterns ────────────────────────────────────────────────

_OFF_TOPIC_PATTERNS = (
    r"\b(?:weather|forecast|rainy?|snowy?|sunny|climate)\b",
    r"\b(?:recipe|cook(?:ing)?|bake|baking|ingredients|pancake|pizza|burger|salad|dinner|lunch|breakfast)\b",
    r"\b(?:movie|movies|film|films|actor|actress|cinema|hollywood|bollywood|song|songs|lyrics|album|singer)\b",
    r"\b(?:politics|political|president|election|vote|voting|parliament|congress|democrat|republican)\b",
    r"\b(?:hotel|hotels|flight|flights|vacation|tourism|travel\s+to|trip\s+to|holiday)\b",
    r"\b(?:joke|jokes|funny|riddle|riddles|how\s+are\s+you|who\s+are\s+you|what\s+is\s+your\s+name|dating|relationship)\b",
)

_PROGRAMMING_INDICATORS = (
    r"\b(?:algorithm|function|code|program|method|class|variable|loop|recursion|recursive)\b",
    r"\b(?:array|arrays|list|lists|string|strings|matrix|vector|stack|queue|tree|graph|heap|hash|map|set)\b",
    r"\b(?:sort|sorted|sorting|search|searching|reverse|reversed|reversal|traverse|traversal|swap)\b",
    r"\b(?:sum|difference|product|division|modulo|remainder|quotient|average|mean)\b",
    r"\b(?:max|min|maximum|minimum|greatest|smallest|largest|second\s+largest)\b",
    r"\b(?:even|odd|prime|fibonacci|factorial|palindrome|anagram|gcd|lcm|divisor|multiple)\b",
    r"\b(?:integer|integers|float|number|numbers|digit|digits|char|character|characters|boolean|binary|decimal)\b",
    r"\b(?:target|index|indices|pointer|pointers|element|elements|item|items|node|nodes|value|values)\b",
    r"\b(?:input|output|return|print|given|find|count|calculate|check|determine|generate|convert|solve|implement)\b",
    r"\b(?:leetcode|problem\s*#?\d+|lc\s*#?\d+|two\s+sum|merge\s+intervals)\b",
)

_OFF_TOPIC_MESSAGE = (
    "Pebble Playground is specialized for programming, data structures, and algorithms. "
    "Please enter a programming problem or coding challenge (e.g., 'Find two numbers that sum to target', "
    "'Check if a string is a palindrome', or 'Calculate the factorial of a number')."
)

# ─── LLM Prompts ──────────────────────────────────────────────────────────────

_EXPLAIN_SYSTEM = """You are Pebble, a friendly DSA tutor. The user has pasted code.
Your task:
1. Identify the algorithm or data structure used.
2. Write a concise, beginner-friendly explanation (3-6 sentences).
3. Write a one-sentence approach summary.

Output ONLY valid JSON with this exact schema (no markdown):
{
  "approach": "<one sentence summary>",
  "explanation": "<step-by-step beginner-friendly explanation>",
  "solution_code": "<the user's code, cleaned up if needed>"
}"""

_SOLVE_SYSTEM = """You are Pebble, a friendly DSA tutor. The user has described a programming problem.
Your task:
1. Write a clean, working solution in the requested language.
2. Write a concise, beginner-friendly explanation (3-6 sentences).
3. Write a one-sentence approach summary.

Output ONLY valid JSON with this exact schema (no markdown):
{
  "approach": "<one sentence summary>",
  "explanation": "<step-by-step beginner-friendly explanation>",
  "solution_code": "<clean solution code>"
}"""


def _safe_json_parse(raw: str) -> Optional[dict]:
    """Strip markdown fences and parse JSON."""
    import json

    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except Exception:
        return None


class PlaygroundService:
    """Service powering the /playground endpoint."""

    def __init__(
        self,
        problem_service: Optional[ProblemService] = None,
        solution_repo: Optional[SolutionRepository] = None,
    ):
        self._problem_service = problem_service or ProblemService()
        self._solution_repo = solution_repo or SolutionRepository()

    # ── Public entry point ─────────────────────────────────────────────────────

    def run(self, db: Session, req: PlaygroundRequest) -> PlaygroundResponse:
        """Dispatch to the appropriate handler based on mode."""
        try:
            if req.mode == "explain":
                return self._explain(db, req)
            else:
                return self._solve(db, req)
        except Exception as exc:
            logger.error("PlaygroundService.run failed: %s", type(exc).__name__)
            return PlaygroundResponse(
                status="error",
                mode=req.mode,
                language=req.language,
                error="Something went wrong while processing your request. Please try again.",
            )

    # ── Explain mode ───────────────────────────────────────────────────────────

    def _explain(self, db: Session, req: PlaygroundRequest) -> PlaygroundResponse:
        """Explain user-pasted code using the LLM."""
        code = (req.code or "").strip()
        if not code:
            return PlaygroundResponse(
                status="error",
                mode="explain",
                language=req.language,
                error="No code provided to explain.",
            )

        underlying = detect_underlying_algorithm(code)
        default_approach = underlying or "Custom code execution"
        default_explanation = (
            f"Analyzed implementation: {underlying}. "
            "Pebble will trace step-by-step execution across your data structures."
            if underlying
            else "User-submitted code ready for execution and analysis."
        )

        provider = get_llm_provider()
        if provider is None:
            # LLM not configured — return passthrough with heuristic algorithm detection if available
            return PlaygroundResponse(
                status="ok",
                mode="explain",
                language=req.language,
                solution_code=code,
                approach=default_approach,
                explanation=default_explanation,
                source="passthrough",
            )

        custom_ctx = f"\nCustom test input provided: {req.custom_input}" if req.custom_input else ""
        user_prompt = (
            f"Language: {req.language}\n\nCode:\n```\n{code}\n```{custom_ctx}\n\n"
            "Please explain the algorithm and return JSON as instructed."
        )

        try:
            raw = provider.complete(_EXPLAIN_SYSTEM, user_prompt)
            parsed = _safe_json_parse(raw)
            if parsed:
                expl = parsed.get("explanation") or parsed.get("reply") or default_explanation
                appr = parsed.get("approach") or default_approach
                sol_code = parsed.get("solution_code") or code
                return PlaygroundResponse(
                    status="ok",
                    mode="explain",
                    language=req.language,
                    solution_code=sol_code,
                    explanation=expl,
                    approach=appr,
                    source="llm",
                )
        except Exception as exc:
            logger.warning("LLM explain call failed: %s", type(exc).__name__)

        # Fallback: return code with heuristic explanation
        return PlaygroundResponse(
            status="ok",
            mode="explain",
            language=req.language,
            solution_code=code,
            approach=default_approach,
            explanation=default_explanation,
            source="passthrough",
        )

    def _validate_problem_scope(self, problem_text: str) -> Tuple[bool, Optional[str]]:
        """Validate whether the problem description is programming/DSA related.

        Rules:
        - Prompt injection attempts are strictly rejected.
        - Clearly off-topic queries (weather, recipes, movies, politics, vacation, chitchat)
          are rejected without calling an external LLM.
        - Valid programming and DSA problems (including beginner questions like even/odd,
          factorial, max of three numbers, prime check) are accepted.
        - Text containing DSA keywords from dsa_keywords or programming indicators are accepted.
        """
        raw = problem_text.strip()
        lower = raw.lower()

        # 1. Prompt-injection check
        if has_prompt_injection(lower):
            return False, _OFF_TOPIC_MESSAGE

        # 2. Strong DSA keyword match or known problem number / LeetCode URL -> always valid
        if contains_dsa_keyword(lower) or re.search(r"\b(?:leetcode|problem\s*#?\d+|lc\s*#?\d+)\b", lower):
            return True, None

        # 3. Check for clearly off-topic topics
        has_off_topic = any(re.search(pat, lower) for pat in _OFF_TOPIC_PATTERNS)
        has_programming_indicator = any(re.search(pat, lower) for pat in _PROGRAMMING_INDICATORS)

        if has_off_topic and not has_programming_indicator:
            return False, _OFF_TOPIC_MESSAGE

        # 4. If neither off-topic nor programming indicators, check if too brief / non-sensical
        words = lower.split()
        if len(words) < 2 and not has_programming_indicator:
            return False, _OFF_TOPIC_MESSAGE

        # 5. Default to valid (avoids false negatives for nuanced beginner problem descriptions)
        return True, None

    # ── Solve mode ─────────────────────────────────────────────────────────────

    def _solve(self, db: Session, req: PlaygroundRequest) -> PlaygroundResponse:
        """
        Solve a described problem.

        Resolution order:
          1. Validate problem scope (reject clearly off-topic requests).
          2. Try to match a known problem in the DB and return its stored solution.
          3. If no DB match, generate via LLM.
        """
        problem_text = (req.problem or "").strip()
        if not problem_text:
            return PlaygroundResponse(
                status="error",
                mode="solve",
                language=req.language,
                error="No problem description provided.",
            )

        # Off-topic validation
        is_valid, validation_error = self._validate_problem_scope(problem_text)
        if not is_valid:
            return PlaygroundResponse(
                status="error",
                mode="solve",
                language=req.language,
                error=validation_error,
            )

        # Step 2: DB lookup
        db_result = self._try_db_solution(db, problem_text, req.language)
        if db_result:
            return db_result

        # Step 3: LLM generation
        return self._generate_solution(req, problem_text)

    def _try_db_solution(
        self, db: Session, problem_text: str, language: str
    ) -> Optional[PlaygroundResponse]:
        """Search the existing problem/solution DB. Returns None if nothing useful found.

        STRICT RULE: Never returns a solution in a different language from the requested one.
        If no matching language solution exists, returns None to trigger LLM fallback.
        """
        try:
            resolve = self._problem_service.resolve_problem(db, problem_text, language)
            if not resolve.resolved or resolve.problem is None:
                return None

            # 1. Exact solution match already returned in resolve
            if resolve.solution and resolve.solution.language.lower() == language.lower():
                return PlaygroundResponse(
                    status="ok",
                    mode="solve",
                    language=language,
                    solution_code=resolve.solution.code,
                    approach=f"Classic solution for: {resolve.problem.title}",
                    explanation=(
                        f"This is a verified stored solution for **{resolve.problem.title}** in {language}. "
                        "Review the code structure to understand the algorithm."
                    ),
                    source="db",
                )

            # 2. Fallback: Lookup problem entity and fetch available solutions
            problem_item = resolve.problem
            orm_problem = self._problem_service.problem_repo.get_by_external_id(
                db, str(problem_item.id)
            )
            if orm_problem is None:
                orm_problem = self._problem_service.problem_repo.get_by_slug(
                    db, problem_item.slug
                )
            if orm_problem:
                solutions = self._solution_repo.get_by_problem_id(db, orm_problem.id)
                if solutions:
                    # STRICT REQUIREMENT: Only match the exact requested language
                    target_sol = next(
                        (s for s in solutions if s.language.lower() == language.lower()),
                        None,
                    )
                    if target_sol:
                        return PlaygroundResponse(
                            status="ok",
                            mode="solve",
                            language=language,
                            solution_code=target_sol.code,
                            approach=f"Classic solution for: {problem_item.title}",
                            explanation=(
                                f"This is a verified stored solution for **{problem_item.title}** in {language}. "
                                "Review the code structure to understand the algorithm."
                            ),
                            source="db",
                        )
            # If no solution in the requested language exists, return None so LLM fallback generates it
            return None
        except Exception as exc:
            logger.debug("DB lookup in playground failed (non-fatal): %s", type(exc).__name__)
            return None

    def _generate_solution(
        self, req: PlaygroundRequest, problem_text: str
    ) -> PlaygroundResponse:
        """Generate a solution using the configured LLM."""
        provider = get_llm_provider()
        if provider is None:
            return PlaygroundResponse(
                status="ok",
                mode="solve",
                language=req.language,
                solution_code="# LLM not configured — no solution generated",
                approach="LLM not configured.",
                explanation=(
                    "The LLM provider is not configured in this environment. "
                    "Configure INTENT_PROVIDER in the backend .env to enable AI solution generation."
                ),
                source="passthrough",
            )

        custom_ctx = f"\nCustom test input: {req.custom_input}" if req.custom_input else ""
        user_prompt = (
            f"Language: {req.language}\n\nProblem:\n{problem_text}{custom_ctx}\n\n"
            "Please solve this and return JSON as instructed."
        )

        try:
            raw = provider.complete(_SOLVE_SYSTEM, user_prompt)
            parsed = _safe_json_parse(raw)
            if parsed:
                sol_code = parsed.get("solution_code") or ""
                expl = parsed.get("explanation") or parsed.get("reply") or f"Algorithm solution for {problem_text}."
                appr = parsed.get("approach") or f"Optimal algorithm for {problem_text}."
                if not sol_code:
                    sol_code = (
                        f"# Solution for: {problem_text}\n"
                        "def solve(*args):\n"
                        "    # Phase 1 starter implementation\n"
                        "    pass\n"
                    )
                return PlaygroundResponse(
                    status="ok",
                    mode="solve",
                    language=req.language,
                    solution_code=sol_code,
                    explanation=expl,
                    approach=appr,
                    source="llm",
                )
        except Exception as exc:
            logger.warning("LLM solve call failed: %s", type(exc).__name__)

        return PlaygroundResponse(
            status="error",
            mode="solve",
            language=req.language,
            error="Could not generate a solution at this time. Please try again.",
        )
