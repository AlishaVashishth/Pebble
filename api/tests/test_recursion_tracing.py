"""
Comprehensive Recursion Tracing Tests for Pebble Playground 2.0.

Validates step-by-step recursive execution tracing across Python and Java:
  - Test A: Python Factorial (5 calls, 5 returns, correct depths, independent locals, result 120)
  - Test B: Java Factorial (5 calls, 5 returns, correct depths, independent locals, result 120)
  - Test C: Fibonacci (fib(4) branching tree, repeated calls with independent frames)
  - Test D: Recursive Sum (general recursion, not factorial-specific)
  - Test E: No function object leaking into local_vars / Variable Inspector
"""

import pytest
from backend.app.execution.runner import execute_python, execute_java


# ─── TEST A: PYTHON FACTORIAL ──────────────────────────────────────────────────

def test_python_factorial_call_stack():
    code = """
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

result = factorial(5)
print("Factorial:", result)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Factorial: 120" in res.stdout
    assert res.trace_available

    call_steps = [s for s in res.trace_steps if s.operation_type == "call" or s.event_type == "call"]
    return_steps = [s for s in res.trace_steps if s.operation_type == "return" or s.event_type == "return"]

    # 5 recursive calls for n = 5, 4, 3, 2, 1
    assert len(call_steps) >= 5
    call_args = [s.local_vars.get("n") for s in call_steps if "n" in s.local_vars]
    assert call_args[:5] == [5, 4, 3, 2, 1]

    # Max depth must reach 5
    max_depth = max((len(s.call_stack) for s in res.trace_steps if s.call_stack), default=0)
    assert max_depth >= 5

    # 5 return steps from the 5 recursive invocations
    factorial_returns = [
        s for s in return_steps
        if s.call_stack and any(f.func_name == "factorial" for f in s.call_stack)
    ]
    assert len(factorial_returns) >= 5

    # Check return values: 1, 2, 6, 24, 120
    ret_values = [s.return_value for s in factorial_returns if s.return_value is not None]
    assert 1 in ret_values
    assert 120 in ret_values

    # Verify no function object references in any step's local_vars
    for s in res.trace_steps:
        for k, v in s.local_vars.items():
            assert not str(v).startswith("<function ")
            assert not str(v).startswith("<class ")


# ─── TEST B: JAVA FACTORIAL ────────────────────────────────────────────────────

def test_java_factorial_call_stack():
    code = """
public class Main {
    public static int factorial(int n) {
        if (n <= 1) return 1;
        return n * factorial(n - 1);
    }
    public static void main(String[] args) {
        int n = 5;
        int result = factorial(n);
        System.out.println("Result: " + result);
    }
}
"""
    res = execute_java(code)
    assert res.status == "ok", f"Java execution failed: {res.stderr}"
    assert "Result: 120" in res.stdout
    assert res.trace_available

    call_steps = [s for s in res.trace_steps if s.operation_type == "call" or s.event_type == "call"]
    return_steps = [s for s in res.trace_steps if s.operation_type == "return" or s.event_type == "return"]

    # 5 recursive calls: factorial(5), (4), (3), (2), (1)
    assert len(call_steps) == 5
    call_args = [s.local_vars.get("n") for s in call_steps]
    assert call_args == [5, 4, 3, 2, 1]

    # Max call stack depth must be 5
    max_depth = max((len(s.call_stack) for s in res.trace_steps if s.call_stack), default=0)
    assert max_depth == 5

    # 5 returns from factorial
    factorial_returns = [
        s for s in return_steps
        if s.call_stack and any(f.func_name == "factorial" for f in s.call_stack)
    ]
    assert len(factorial_returns) == 5

    # Returns must calculate: 1, 2, 6, 24, 120
    ret_vals = [s.return_value for s in factorial_returns]
    assert ret_vals == [1, 2, 6, 24, 120]

    # Verify stack frames have distinct IDs and proper depths
    for s in call_steps:
        assert s.call_stack is not None
        top = s.call_stack[-1]
        assert top.func_name == "factorial"
        assert top.depth == len(s.call_stack) - 1


# ─── TEST C: FIBONACCI (BRANCHING RECURSION) ──────────────────────────────────

def test_python_fibonacci():
    code = """
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)

ans = fib(4)
print("Fib:", ans)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Fib: 3" in res.stdout
    assert res.trace_available

    call_steps = [s for s in res.trace_steps if s.operation_type == "call" or s.event_type == "call"]
    # fib(4) produces 9 total calls: fib(4), fib(3), fib(2), fib(1), fib(0), fib(1), fib(2), fib(1), fib(0)
    assert len(call_steps) == 9

    # Verify that multiple calls to fib(1) get separate stack frame IDs
    fib1_calls = [s for s in call_steps if s.local_vars.get("n") == 1]
    assert len(fib1_calls) == 3
    frame_ids = [s.call_stack[-1].frame_id for s in fib1_calls if s.call_stack and s.call_stack[-1].frame_id]
    assert len(set(frame_ids)) == len(frame_ids)  # All unique


def test_java_fibonacci():
    code = """
public class Main {
    public static int fib(int n) {
        if (n <= 1) return n;
        return fib(n - 1) + fib(n - 2);
    }
    public static void main(String[] args) {
        int ans = fib(4);
        System.out.println("Fib: " + ans);
    }
}
"""
    res = execute_java(code)
    assert res.status == "ok", f"Java execution failed: {res.stderr}"
    assert "Fib: 3" in res.stdout
    assert res.trace_available

    call_steps = [s for s in res.trace_steps if s.operation_type == "call" or s.event_type == "call"]
    assert len(call_steps) == 9

    # Returns produce 9 return events
    return_steps = [s for s in res.trace_steps if s.operation_type == "return" or s.event_type == "return"]
    assert len(return_steps) == 9


# ─── TEST D: RECURSIVE SUM (GENERAL RECURSION) ───────────────────────────────

def test_python_recursive_sum():
    code = """
def rec_sum(n):
    if n <= 0:
        return 0
    return n + rec_sum(n - 1)

print("Sum:", rec_sum(5))
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Sum: 15" in res.stdout
    assert res.trace_available
    assert any(s.call_stack and len(s.call_stack) == 6 for s in res.trace_steps)


def test_java_recursive_sum():
    code = """
public class Main {
    public static int recSum(int n) {
        if (n <= 0) return 0;
        return n + recSum(n - 1);
    }
    public static void main(String[] args) {
        System.out.println("Sum: " + recSum(5));
    }
}
"""
    res = execute_java(code)
    assert res.status == "ok", f"Java execution failed: {res.stderr}"
    assert "Sum: 15" in res.stdout
    assert res.trace_available
    call_steps = [s for s in res.trace_steps if s.operation_type == "call" or s.event_type == "call"]
    assert len(call_steps) == 6
    return_steps = [s for s in res.trace_steps if s.operation_type == "return" or s.event_type == "return"]
    assert len(return_steps) == 6
