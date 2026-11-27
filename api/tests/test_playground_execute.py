"""Tests for sandboxed code execution and POST /playground/execute endpoint (Phase 2)."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.app.core.security import create_access_token
from backend.app.db.session import get_db
from backend.app.execution.runner import (
    execute_code,
    execute_cpp,
    execute_java,
    execute_python,
)
from backend.app.execution.sandbox import get_sanitized_env
from backend.app.execution.schemas import ExecutionResult, TraceStep
from backend.app.main import create_app
from backend.app.models.user import User
from backend.app.schemas.playground import ExecuteRequest, ExecuteResponse
from backend.app.services.video_service import VideoService


# ---------------------------------------------------------------------------
# 1. Environment Sanitization & Security Tests
# ---------------------------------------------------------------------------


def test_sanitized_env_excludes_sensitive_keys():
    """Environment sanitization strips secrets like DATABASE_URL, SECRET_KEY, API keys."""
    with patch.dict(
        "os.environ",
        {
            "DATABASE_URL": "postgresql://secret_user:secret_pass@localhost/db",
            "SECRET_KEY": "super_secret_jwt_key",
            "OPENAI_API_KEY": "sk-1234567890abcdef",
            "PATH": "C:\\Windows\\system32",
            "SYSTEMROOT": "C:\\Windows",
        },
        clear=True,
    ):
        clean = get_sanitized_env()
        assert "PATH" in clean
        assert "SYSTEMROOT" in clean
        assert "DATABASE_URL" not in clean
        assert "SECRET_KEY" not in clean
        assert "OPENAI_API_KEY" not in clean


# ---------------------------------------------------------------------------
# 2. Python Execution Tests
# ---------------------------------------------------------------------------


def test_python_simple_execution():
    """Python basic print statement executes and captures stdout."""
    res = execute_python('print("Hello from Python")')
    assert res.status == "ok"
    assert "Hello from Python" in res.stdout
    assert res.exit_code == 0
    assert res.timed_out is False
    assert res.language == "python"


def test_python_custom_stdin():
    """Python execution correctly reads custom input from stdin."""
    code = """\
name = input()
age = int(input())
print(f"User {name} is {age} years old")
"""
    stdin_data = "Alice\n25\n"
    res = execute_python(code, stdin_text=stdin_data)
    assert res.status == "ok"
    assert "User Alice is 25 years old" in res.stdout


def test_python_execution_traces_variables_and_arrays():
    """Python execution generates detailed trace steps capturing array and variable mutations."""
    code = """\
nums = [3, 1, 2]
n = len(nums)
total = 0
for x in nums:
    total += x
print("Total:", total)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Total: 6" in res.stdout
    assert res.trace_available is True
    assert len(res.trace_steps) > 0

    # Verify that variable names and values appear in trace steps
    all_var_keys = set()
    for step in res.trace_steps:
        all_var_keys.update(step.local_vars.keys())

    assert "nums" in all_var_keys
    assert "n" in all_var_keys
    assert "total" in all_var_keys
    assert "x" in all_var_keys


def test_python_trace_pointers_and_window():
    """Python execution detects pointers, active window, and explanation."""
    code = """\
arr = [2, 3, 1, 2, 4, 3]
target = 7
left = 0
window_sum = 0
for right in range(len(arr)):
    window_sum += arr[right]
    while window_sum >= target:
        window_sum -= arr[left]
        left += 1
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert res.trace_available is True
    assert any("left" in s.pointers for s in res.trace_steps)
    assert any("right" in s.pointers for s in res.trace_steps)
    assert any(s.window is not None for s in res.trace_steps)
    assert any(len(s.explanation) > 0 for s in res.trace_steps)


def test_python_syntax_error():
    """Python syntax error returns status 'compile_error' with traceback in stderr."""
    res = execute_python("def broken_syntax(")
    assert res.status == "compile_error"
    assert res.exit_code != 0
    assert "SyntaxError" in res.stderr


def test_python_runtime_error():
    """Python runtime error (ZeroDivisionError) returns status 'error'."""
    res = execute_python("x = 10 / 0")
    assert res.status == "error"
    assert res.exit_code != 0
    assert "ZeroDivisionError" in res.stderr


def test_python_timeout():
    """Python infinite loop times out safely without freezing the server."""
    res = execute_python("while True: pass", timeout=2)
    assert res.status == "timeout"
    assert res.timed_out is True
    assert "timed out" in res.stderr.lower()


# ---------------------------------------------------------------------------
# 3. Java Execution Tests
# ---------------------------------------------------------------------------


def test_java_simple_execution():
    """Java code compiles and executes successfully."""
    code = """\
public class Main {
    public static void main(String[] args) {
        System.out.println("Hello from Java");
    }
}
"""
    res = execute_java(code)
    assert res.status == "ok"
    assert "Hello from Java" in res.stdout
    assert res.exit_code == 0
    assert res.language == "java"


def test_java_custom_stdin():
    """Java execution reads custom input via Scanner."""
    code = """\
import java.util.Scanner;

public class Solution {
    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in);
        int a = sc.nextInt();
        int b = sc.nextInt();
        System.out.println("Sum: " + (a + b));
    }
}
"""
    res = execute_java(code, stdin_text="40 2")
    assert res.status == "ok"
    assert "Sum: 42" in res.stdout


def test_java_bubble_sort_tracing():
    """Java code execution captures line-by-line runtime trace, arrays, and variables."""
    code = """\
public class BubbleSort {
    public static void main(String[] args) {
        int[] arr = {5, 1, 4, 2, 8};
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
        System.out.println("Sorted: " + java.util.Arrays.toString(arr));
    }
}
"""
    res = execute_java(code)
    assert res.status == "ok"
    assert "Sorted: [1, 2, 4, 5, 8]" in res.stdout
    assert res.trace_available is True
    assert len(res.trace_steps) > 5
    # Verify that array and pointers were captured
    first_step = res.trace_steps[0]
    assert "arr" in first_step.local_vars
    assert first_step.active_array == "arr"



def test_java_compile_error():
    """Java code with compilation errors returns status 'compile_error'."""
    code = """\
public class Main {
    public static void main(String[] args) {
        int x = "incompatible types";
    }
}
"""
    res = execute_java(code)
    assert res.status == "compile_error"
    assert res.exit_code != 0
    assert len(res.stderr) > 0


# ---------------------------------------------------------------------------
# 4. C++ Execution Tests
# ---------------------------------------------------------------------------


def test_cpp_simple_execution():
    """C++ code compiles and runs with g++."""
    code = """\
#include <iostream>

int main() {
    std::cout << "Hello from C++" << std::endl;
    return 0;
}
"""
    res = execute_cpp(code)
    assert res.status == "ok"
    assert "Hello from C++" in res.stdout
    assert res.exit_code == 0
    assert res.language == "cpp"


def test_cpp_custom_stdin():
    """C++ execution reads custom input from std::cin."""
    code = """\
#include <iostream>

int main() {
    int x, y;
    if (std::cin >> x >> y) {
        std::cout << "Product: " << (x * y) << std::endl;
    }
    return 0;
}
"""
    res = execute_cpp(code, stdin_text="7 6")
    assert res.status == "ok"
    assert "Product: 42" in res.stdout


def test_cpp_compile_error():
    """C++ syntax error returns status 'compile_error'."""
    code = """\
#include <iostream>
int main() {
    syntax error here;
}
"""
    res = execute_cpp(code)
    assert res.status == "compile_error"
    assert res.exit_code != 0


# ---------------------------------------------------------------------------
# 5. Dispatcher & Unsupported Languages
# ---------------------------------------------------------------------------


def test_execute_code_unsupported_language():
    """Unsupported language returns status 'unavailable'."""
    res = execute_code(language="rust", code="fn main() {}")
    assert res.status == "unavailable"
    assert res.language_unavailable is True
    assert "not supported" in res.stderr


# ---------------------------------------------------------------------------
# 6. POST /playground/execute API Endpoint Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def playground_client():
    """Provide in-memory TestClient with patched VideoService and DB."""
    with patch.object(VideoService, "resume_uncompleted_jobs"):
        app = create_app()
        mock_db = MagicMock()

        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()


def test_execute_endpoint_unauthorized(playground_client: TestClient):
    """POST /playground/execute without auth token returns 401."""
    res = playground_client.post(
        "/playground/execute",
        json={"language": "python", "code": "print('test')"},
    )
    assert res.status_code == 401


def test_execute_endpoint_authorized(playground_client: TestClient):
    """POST /playground/execute with valid auth token runs code and returns ExecuteResponse."""
    fake_user = User(
        email="exec_user@example.com",
        name="Exec User",
        password_hash="fakehash",
    )
    fake_user.id = "33333333-3333-3333-3333-333333333333"
    token = create_access_token(str(fake_user.id))

    with patch("backend.app.core.dependencies.UserRepository.get_by_id", return_value=fake_user):
        res = playground_client.post(
            "/playground/execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "language": "python",
                "code": "a = [10, 20]; print('Sum:', sum(a))",
                "custom_input": "",
                "timeout_seconds": 10,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "Sum: 30" in data["stdout"]
        assert data["language"] == "python"
        assert data["trace_available"] is True
        assert len(data["trace_steps"]) > 0


def test_execute_endpoint_validation_empty_code(playground_client: TestClient):
    """POST /playground/execute with empty code returns 422 Unprocessable Entity."""
    fake_user = User(
        email="exec_user@example.com",
        name="Exec User",
        password_hash="fakehash",
    )
    fake_user.id = "33333333-3333-3333-3333-333333333333"
    token = create_access_token(str(fake_user.id))

    with patch("backend.app.core.dependencies.UserRepository.get_by_id", return_value=fake_user):
        res = playground_client.post(
            "/playground/execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"language": "python", "code": ""},
        )
        assert res.status_code == 422


def test_python_function_only_auto_driver():
    """Function-only Python code is automatically augmented with driver code and traced."""
    code = """
def twoSum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
    return []
"""
    res = execute_python(code, stdin_text="[2, 7, 11, 15]\n9")
    assert res.status == "ok"
    assert res.trace_available is True
    assert len(res.trace_steps) > 5
    assert "Result: [0, 1]" in res.stdout
    # Verify array variable is captured in trace steps
    array_steps = [s for s in res.trace_steps if s.active_array == "nums"]
    assert len(array_steps) > 0


def test_python_class_solution_auto_driver():
    """Class Solution pattern is automatically augmented with driver code and traced."""
    code = """
class Solution:
    def maxSubArray(self, nums):
        max_so_far = nums[0]
        curr_max = nums[0]
        for x in nums[1:]:
            curr_max = max(x, curr_max + x)
            max_so_far = max(max_so_far, curr_max)
        return max_so_far
"""
    res = execute_python(code, stdin_text="[-2, 1, -3, 4, -1, 2, 1, -5, 4]")
    assert res.status == "ok"
    assert res.trace_available is True
    assert len(res.trace_steps) > 5
    assert "Result: 6" in res.stdout

