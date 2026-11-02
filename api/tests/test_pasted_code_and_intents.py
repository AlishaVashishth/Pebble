"""Tests for pasted code detection and intent classification (9 required cases)."""

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.core.code_detection import detect_pasted_code, detect_underlying_algorithm
from backend.app.db.base import Base
from backend.app.integrations.llm.mock import MockLLMProvider
from backend.app.services.ask_service import OUT_OF_SCOPE_MESSAGE, AskService
from backend.app.services.intent_service import IntentService


@pytest.fixture
def sqlite_session():
    """Isolated in-memory SQLite session for tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()

# 1. The string-reverse code from the prompt
PYTHON_STRING_REVERSE = '''text = "Hello World"
reversed_text = text[::-1]
print(reversed_text)  # Output: "dlroW olleH"'''

# 7. Java bubble sort snippet
JAVA_BUBBLE_SORT = """void bubbleSort(int[] arr) {
    int n = arr.length;
    for (int i = 0; i < n - 1; i++) {
        for (int j = 0; j < n - i - 1; j++) {
            if (arr[j] > arr[j + 1]) {
                int temp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = temp;
            }
        }
    }
}"""

# 8. Fenced python block with a for loop
FENCED_PYTHON_FOR_LOOP = """```python
for i in range(10):
    print(i)
```"""


@pytest.fixture
def mock_llm_provider():
    provider = MockLLMProvider()
    provider.reset()
    return provider


@pytest.mark.parametrize(
    "query, expected_intent",
    [
        (PYTHON_STRING_REVERSE, "user_code"),
        ("two sum", "repo question"),
        ("leetcode 56", "repo question"),
        ("merge two sorted arrays", "described problem"),
        ("I'm on holiday, generate a video", "out_of_scope"),
        ("what's the weather", "out_of_scope"),
        (JAVA_BUBBLE_SORT, "user_code"),
        (FENCED_PYTHON_FOR_LOOP, "user_code"),
        ("explain binary search trees", "topic request"),
    ],
)
def test_nine_required_query_intents(mock_llm_provider, query, expected_intent):
    """Verify all 9 queries are classified into their expected intents."""
    service = IntentService(provider=mock_llm_provider)
    actual_intent = service.classify_intent(query)
    assert actual_intent == expected_intent, f"Query '{query[:30]}...' expected {expected_intent}, got {actual_intent}"


def test_string_reverse_code_detection():
    """Verify string reversal snippet is detected as Python code."""
    is_code, code, lang, remaining = detect_pasted_code(PYTHON_STRING_REVERSE)
    assert is_code is True
    assert code == PYTHON_STRING_REVERSE
    assert lang == "python"
    assert remaining == ""

    # Check underlying algorithm detection (two pointers swapping)
    algo = detect_underlying_algorithm(code)
    assert algo is not None
    assert "Two Pointers" in algo


def test_string_reverse_in_ask_service(sqlite_session, monkeypatch, mock_llm_provider):
    """Verify pasting Python string reverse code routes to user_code flow and enables generation."""
    test_settings = Settings(INTENT_PROVIDER="mock")
    monkeypatch.setattr("backend.app.services.ask_service.get_settings", lambda: test_settings)

    intent_service = IntentService(provider=mock_llm_provider)
    ask_service = AskService(intent_service=intent_service)

    resp = ask_service.ask(db=sqlite_session, text=PYTHON_STRING_REVERSE, programming_language="python")

    assert resp.status == "concept"
    assert resp.can_generate is True
    assert resp.solution is not None
    assert resp.solution.code == PYTHON_STRING_REVERSE
    assert resp.solution.validated is False
    assert resp.video_request is not None
    assert resp.video_request.user_code == PYTHON_STRING_REVERSE
    # Video request text mentions two-pointer string reversal
    assert "Two Pointers" in resp.video_request.text or "String Reversal" in resp.video_request.text


def test_out_of_scope_message_mentions_pasting_code(sqlite_session, monkeypatch, mock_llm_provider):
    """Verify out-of-scope response invites the user to paste their own code."""
    test_settings = Settings(INTENT_PROVIDER="mock")
    monkeypatch.setattr("backend.app.services.ask_service.get_settings", lambda: test_settings)

    intent_service = IntentService(provider=mock_llm_provider)
    ask_service = AskService(intent_service=intent_service)

    resp = ask_service.ask(db=sqlite_session, text="what's the weather", programming_language="python")

    assert resp.status == "out_of_scope"
    assert resp.can_generate is False
    assert "paste your own code" in resp.message
    assert OUT_OF_SCOPE_MESSAGE == resp.message
