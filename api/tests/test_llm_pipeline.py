"""
LLM Input/Output Pipeline Tests — Priority 1 Validation.

Tests exact language matching, provider retry/error handling,
response validation, and provider factory correctness.

All tests use mocks to avoid real API calls unless explicitly noted.
"""

import json
import sys
import os
import types
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure the api/ directory is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_provider(return_value: str = None, raise_exc: Exception = None):
    """Create a mock LLMProvider whose .complete() either returns a value or raises."""
    provider = MagicMock()
    if raise_exc:
        provider.complete.side_effect = raise_exc
    else:
        provider.complete.return_value = return_value
    return provider


# ---------------------------------------------------------------------------
# 1. Language normalization
# ---------------------------------------------------------------------------

class TestLanguageNormalization(unittest.TestCase):
    def setUp(self):
        from backend.app.core.language import normalize_language, languages_match, format_language_display
        self.normalize = normalize_language
        self.match = languages_match
        self.display = format_language_display

    def test_cpp_aliases(self):
        self.assertEqual(self.normalize("C++"), "cpp")
        self.assertEqual(self.normalize("c++"), "cpp")
        self.assertEqual(self.normalize("cpp"), "cpp")
        self.assertEqual(self.normalize("cplusplus"), "cpp")

    def test_python_aliases(self):
        self.assertEqual(self.normalize("Python"), "python")
        self.assertEqual(self.normalize("py"), "python")
        self.assertEqual(self.normalize("python3"), "python")

    def test_java_normalized(self):
        self.assertEqual(self.normalize("Java"), "java")
        self.assertEqual(self.normalize("JAVA"), "java")

    def test_languages_match_same(self):
        self.assertTrue(self.match("java", "java"))
        self.assertTrue(self.match("Java", "java"))
        self.assertTrue(self.match("C++", "cpp"))
        self.assertTrue(self.match("python3", "Python"))

    def test_languages_match_different(self):
        self.assertFalse(self.match("java", "python"))
        self.assertFalse(self.match("cpp", "java"))
        self.assertFalse(self.match("python", "javascript"))

    def test_languages_match_none(self):
        self.assertFalse(self.match(None, "java"))
        self.assertFalse(self.match("java", None))
        self.assertFalse(self.match(None, None))

    def test_display_names(self):
        self.assertEqual(self.display("cpp"), "C++")
        self.assertEqual(self.display("python"), "Python")
        self.assertEqual(self.display("java"), "Java")


# ---------------------------------------------------------------------------
# 2. Provider factory
# ---------------------------------------------------------------------------

class TestProviderFactory(unittest.TestCase):

    def test_provider_factory_off(self):
        with patch("backend.app.integrations.llm.get_settings") as mock_settings:
            mock_settings.return_value.INTENT_PROVIDER = "off"
            from backend.app.integrations.llm import get_llm_provider
            result = get_llm_provider()
            self.assertIsNone(result)

    def test_provider_factory_mock(self):
        with patch("backend.app.integrations.llm.get_settings") as mock_settings:
            mock_settings.return_value.INTENT_PROVIDER = "mock"
            from backend.app.integrations.llm import get_llm_provider, MockLLMProvider
            result = get_llm_provider()
            self.assertIsInstance(result, MockLLMProvider)

    def test_provider_factory_groq(self):
        with patch("backend.app.integrations.llm.get_settings") as mock_settings:
            cfg = mock_settings.return_value
            cfg.INTENT_PROVIDER = "groq"
            cfg.GROQ_API_KEY = "test-groq-key"
            cfg.GROQ_MODEL = "some-model"
            cfg.INTENT_TIMEOUT_SECONDS = 30.0
            from backend.app.integrations.llm import get_llm_provider, GroqProvider
            result = get_llm_provider()
            self.assertIsInstance(result, GroqProvider)

    def test_provider_factory_gemini(self):
        with patch("backend.app.integrations.llm.get_settings") as mock_settings:
            cfg = mock_settings.return_value
            cfg.INTENT_PROVIDER = "gemini"
            cfg.GEMINI_API_KEY = "test-gemini-key"
            cfg.GEMINI_MODEL = "gemini-1.5-flash"
            cfg.INTENT_TIMEOUT_SECONDS = 30.0
            from backend.app.integrations.llm import get_llm_provider, GeminiProvider
            result = get_llm_provider()
            self.assertIsInstance(result, GeminiProvider)

    def test_provider_factory_unknown(self):
        with patch("backend.app.integrations.llm.get_settings") as mock_settings:
            mock_settings.return_value.INTENT_PROVIDER = "unknown_provider_xyz"
            from backend.app.integrations.llm import get_llm_provider
            result = get_llm_provider()
            self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 3. Retry logic
# ---------------------------------------------------------------------------

class TestRetryLogic(unittest.TestCase):
    def setUp(self):
        from backend.app.integrations.llm.retry import execute_with_retry
        self.execute_with_retry = execute_with_retry

    def test_success_no_retry(self):
        call_count = [0]
        def fn():
            call_count[0] += 1
            return "ok"
        result = self.execute_with_retry(fn)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 1)

    def test_retry_on_503_then_success(self):
        import httpx
        call_count = [0]
        def fn():
            call_count[0] += 1
            if call_count[0] < 2:
                mock_response = MagicMock()
                mock_response.status_code = 503
                raise httpx.HTTPStatusError("service unavailable", request=MagicMock(), response=mock_response)
            return "recovered"
        result = self.execute_with_retry(fn, base_delay=0.0)
        self.assertEqual(result, "recovered")
        self.assertEqual(call_count[0], 2)

    def test_no_retry_on_401(self):
        import httpx
        call_count = [0]
        def fn():
            call_count[0] += 1
            mock_response = MagicMock()
            mock_response.status_code = 401
            raise httpx.HTTPStatusError("unauthorized", request=MagicMock(), response=mock_response)
        with self.assertRaises(httpx.HTTPStatusError):
            self.execute_with_retry(fn, base_delay=0.0)
        self.assertEqual(call_count[0], 1)  # No retries for 401

    def test_exhaust_retries_raises(self):
        import httpx
        call_count = [0]
        def fn():
            call_count[0] += 1
            mock_response = MagicMock()
            mock_response.status_code = 503
            raise httpx.HTTPStatusError("unavailable", request=MagicMock(), response=mock_response)
        with self.assertRaises(httpx.HTTPStatusError):
            self.execute_with_retry(fn, max_retries=2, base_delay=0.0)
        self.assertEqual(call_count[0], 3)  # 1 initial + 2 retries

    def test_retry_on_network_error_then_success(self):
        import httpx
        call_count = [0]
        def fn():
            call_count[0] += 1
            if call_count[0] < 2:
                raise httpx.TimeoutException("timeout")
            return "network_ok"
        result = self.execute_with_retry(fn, base_delay=0.0)
        self.assertEqual(result, "network_ok")


# ---------------------------------------------------------------------------
# 4. Playground service language matching
# ---------------------------------------------------------------------------

class TestPlaygroundServiceLanguageMatching(unittest.TestCase):
    """Test that _try_db_solution returns None when language doesn't match."""

    def _make_service(self):
        from backend.app.services.playground_service import PlaygroundService
        svc = PlaygroundService.__new__(PlaygroundService)
        svc._problem_service = MagicMock()
        svc._solution_repo = MagicMock()
        return svc

    def _make_solution(self, language: str, code: str = "code"):
        sol = MagicMock()
        sol.language = language
        sol.code = code
        return sol

    def _make_problem(self, title: str = "Test Problem", slug: str = "test", id: int = 1):
        p = MagicMock()
        p.title = title
        p.slug = slug
        p.id = id
        return p

    def test_exact_language_match_java(self):
        from backend.app.services.playground_service import PlaygroundService
        svc = self._make_service()
        db = MagicMock()

        resolve = MagicMock()
        resolve.resolved = True
        resolve.problem = self._make_problem()
        resolve.solution = self._make_solution("java", "public class Main {}")

        svc._problem_service.resolve_problem.return_value = resolve
        resp = svc._try_db_solution(db, "some problem", "java")
        self.assertIsNotNone(resp)
        self.assertEqual(resp.language, "java")
        self.assertEqual(resp.source, "db")

    def test_no_cross_language_fallback(self):
        """DB has Python only, request Java → must return None."""
        svc = self._make_service()
        db = MagicMock()

        problem = self._make_problem()
        resolve = MagicMock()
        resolve.resolved = True
        resolve.problem = problem
        resolve.solution = self._make_solution("python", "def solve(): pass")

        svc._problem_service.resolve_problem.return_value = resolve
        # Fallback: get_by_problem_id also returns only python solution
        svc._problem_service.problem_repo.get_by_external_id.return_value = MagicMock(id=1)
        svc._solution_repo.get_by_problem_id.return_value = [self._make_solution("python")]

        resp = svc._try_db_solution(db, "some problem", "java")
        # Must return None — Python solution must NOT be returned for Java request
        self.assertIsNone(resp)

    def test_exact_language_match_cpp(self):
        svc = self._make_service()
        db = MagicMock()

        problem = self._make_problem()
        resolve = MagicMock()
        resolve.resolved = True
        resolve.problem = problem
        # resolve.solution is None — trigger fallback search
        resolve.solution = None

        svc._problem_service.resolve_problem.return_value = resolve
        orm_problem = MagicMock(id=5)
        svc._problem_service.problem_repo.get_by_external_id.return_value = orm_problem
        # DB has both Python and C++ solutions
        py_sol = self._make_solution("python", "def x(): pass")
        cpp_sol = self._make_solution("cpp", "#include<bits/stdc++.h>")
        svc._solution_repo.get_by_problem_id.return_value = [py_sol, cpp_sol]

        resp = svc._try_db_solution(db, "some problem", "cpp")
        self.assertIsNotNone(resp)
        self.assertIn("#include", resp.solution_code)

    def test_provider_unavailable_returns_error(self):
        """When provider raises, _generate_solution should not fabricate code."""
        from backend.app.services.playground_service import PlaygroundService
        from backend.app.schemas.playground import PlaygroundRequest
        svc = PlaygroundService.__new__(PlaygroundService)
        svc._problem_service = MagicMock()
        svc._solution_repo = MagicMock()

        req = PlaygroundRequest(
            mode="solve",
            language="java",
            problem="Find max subarray sum of size k",
        )
        with patch("backend.app.services.playground_service.get_llm_provider") as mock_factory:
            mock_provider = MagicMock()
            mock_provider.complete.side_effect = RuntimeError("provider down")
            mock_factory.return_value = mock_provider
            resp = svc._generate_solution(req, "Find max subarray sum of size k")

        self.assertEqual(resp.status, "error")
        # Must not contain fabricated Java-looking boilerplate as the actual solution
        self.assertNotEqual(resp.solution_code, "public class Main { public static void main(String[] args) {} }")

    def test_malformed_provider_response(self):
        """Provider returns invalid JSON → error response, not empty code."""
        from backend.app.services.playground_service import PlaygroundService
        from backend.app.schemas.playground import PlaygroundRequest
        svc = PlaygroundService.__new__(PlaygroundService)
        svc._problem_service = MagicMock()
        svc._solution_repo = MagicMock()

        req = PlaygroundRequest(
            mode="solve",
            language="java",
            problem="Find max subarray sum of size k",
        )
        with patch("backend.app.services.playground_service.get_llm_provider") as mock_factory:
            mock_provider = MagicMock()
            mock_provider.complete.return_value = "this is not json at all!"
            mock_factory.return_value = mock_provider
            resp = svc._generate_solution(req, "Find max subarray sum of size k")

        self.assertIn(resp.status, ("error", "ok"))  # Might degrade gracefully or error
        # Key invariant: code must not be "null" or empty if status is "ok"
        if resp.status == "ok":
            self.assertIsNotNone(resp.solution_code)
            self.assertNotEqual(resp.solution_code.strip(), "")

    def test_custom_input_included_in_prompt(self):
        """Custom input must appear in the user_prompt sent to the provider."""
        from backend.app.services.playground_service import PlaygroundService
        from backend.app.schemas.playground import PlaygroundRequest
        svc = PlaygroundService.__new__(PlaygroundService)
        svc._problem_service = MagicMock()
        svc._solution_repo = MagicMock()

        req = PlaygroundRequest(
            mode="solve",
            language="java",
            problem="Find max subarray sum",
            custom_input="6 3\n2 1 5 1 3 2",
        )
        captured_prompts = {}
        def capture_complete(system_prompt, user_prompt):
            captured_prompts["system"] = system_prompt
            captured_prompts["user"] = user_prompt
            return json.dumps({"solution_code": "public class Main{}", "approach": "sliding window", "explanation": "ok"})

        with patch("backend.app.services.playground_service.get_llm_provider") as mock_factory:
            mock_provider = MagicMock()
            mock_provider.complete.side_effect = capture_complete
            mock_factory.return_value = mock_provider
            svc._generate_solution(req, "Find max subarray sum")

        # The custom_input must appear in the user prompt
        self.assertIn("6 3", captured_prompts.get("user", ""))
        self.assertIn("2 1 5 1 3 2", captured_prompts.get("user", ""))
        # Language must be in prompt
        self.assertIn("java", captured_prompts.get("user", "").lower())

    def test_no_resolved_problem_returns_none(self):
        svc = self._make_service()
        db = MagicMock()
        resolve = MagicMock()
        resolve.resolved = False
        resolve.problem = None
        svc._problem_service.resolve_problem.return_value = resolve
        resp = svc._try_db_solution(db, "nonsense text", "java")
        self.assertIsNone(resp)


# ---------------------------------------------------------------------------
# 5. Safe JSON parse
# ---------------------------------------------------------------------------

class TestSafeJsonParse(unittest.TestCase):
    """Test _safe_json_parse handles edge cases without raising."""

    def setUp(self):
        from backend.app.services import playground_service as ps_module
        self._parse = ps_module._safe_json_parse

    def test_valid_json(self):
        payload = json.dumps({"solution_code": "print(1)", "approach": "brute", "explanation": "ok"})
        result = self._parse(payload)
        self.assertIsNotNone(result)
        self.assertEqual(result["solution_code"], "print(1)")

    def test_json_wrapped_in_markdown(self):
        payload = "```json\n" + json.dumps({"solution_code": "x=1", "approach": "a", "explanation": "b"}) + "\n```"
        result = self._parse(payload)
        self.assertIsNotNone(result)

    def test_invalid_json_returns_none(self):
        result = self._parse("this is not json")
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        result = self._parse("")
        self.assertIsNone(result)

    def test_none_input_returns_none(self):
        result = self._parse(None)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 6. Groq provider HTTP handling
# ---------------------------------------------------------------------------

class TestGroqProvider(unittest.TestCase):
    def setUp(self):
        from backend.app.integrations.llm.groq import GroqProvider
        self.GroqProvider = GroqProvider

    def test_valid_response_parsed(self):
        provider = self.GroqProvider(api_key="test", model="test-model")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"solution_code": "ok"}'}}]
        }
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: s
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            result = provider.complete("system", "user")
        self.assertEqual(result, '{"solution_code": "ok"}')

    def test_empty_choices_raises(self):
        provider = self.GroqProvider(api_key="test", model="test-model")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"choices": []}
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: s
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            with self.assertRaises(RuntimeError):
                provider.complete("system", "user")


if __name__ == "__main__":
    unittest.main(verbosity=2)
