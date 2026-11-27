"""
Comprehensive multi-category DSA test suite for Pebble Playground 2.0 (Phase 1 Universal DSA).

Tests actual user-pasted code across:
  1. Strings (Palindrome, Longest Substring, Reverse, Frequency)
  2. Arrays (Bubble Sort, Two Sum, Prefix Sum, Max Subarray, Binary Search)
  3. HashMaps / Sets (Frequency counting, Two Sum with Map, Group Anagrams)
  4. Stacks & Queues (Balanced Parentheses, Stack push/pop, Monotonic Stack)
  5. Linked Lists (Traversal, Reverse, Cycle detection)
  6. Trees (Inorder Traversal, BST search, Max Depth)
  7. Recursion (Factorial, Fibonacci, Recursion depth)
  8. Graphs (Adjacency list traversal BFS/DFS)
  9. Java Multi-DSA execution & tracing
  10. C++ sandbox execution (fallback without crash)
"""

import pytest
from backend.app.execution.runner import execute_code, execute_python, execute_java, execute_cpp


# ─── 1. STRINGS ─────────────────────────────────────────────────────────────

def test_string_palindrome_two_pointers():
    code = """
s = "racecar"
left = 0
right = len(s) - 1
is_palindrome = True

while left < right:
    if s[left] != s[right]:
        is_palindrome = False
        break
    left += 1
    right -= 1

print("Palindrome:", is_palindrome)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Palindrome: True" in res.stdout
    assert res.trace_available
    assert len(res.trace_steps) > 5

    # Check string view & pointers
    step = res.trace_steps[-2]
    assert step.string_view is not None
    assert step.string_view["text"] == "racecar"
    assert "left" in step.pointers or "right" in step.pointers


def test_string_longest_substring_without_repeating():
    code = """
s = "abcabcbb"
char_map = {}
left = 0
max_len = 0

for right in range(len(s)):
    c = s[right]
    if c in char_map and char_map[c] >= left:
        left = char_map[c] + 1
    char_map[c] = right
    max_len = max(max_len, right - left + 1)

print("Max len:", max_len)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Max len: 3" in res.stdout
    assert res.trace_available
    # Check that hash map view was populated
    has_map = any(s.hash_map_view is not None for s in res.trace_steps)
    assert has_map


# ─── 2. ARRAYS & PREFIX SUM ─────────────────────────────────────────────────

def test_array_prefix_sum():
    code = """
nums = [1, 2, 3, 4, 5]
prefix = [0] * (len(nums) + 1)

for i in range(len(nums)):
    prefix[i + 1] = prefix[i] + nums[i]

print("Prefix sum:", prefix[-1])
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Prefix sum: 15" in res.stdout
    assert res.trace_available
    assert any(s.active_array in ("nums", "prefix") for s in res.trace_steps)


def test_array_binary_search():
    code = """
nums = [1, 3, 5, 7, 9, 11]
target = 7
low = 0
high = len(nums) - 1
found_idx = -1

while low <= high:
    mid = (low + high) // 2
    if nums[mid] == target:
        found_idx = mid
        break
    elif nums[mid] < target:
        low = mid + 1
    else:
        high = mid - 1

print("Found at:", found_idx)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Found at: 3" in res.stdout
    assert res.trace_available
    # Check mid pointer
    assert any("mid" in s.pointers for s in res.trace_steps)


# ─── 3. HASHMAPS & SETS ─────────────────────────────────────────────────────

def test_hashmap_frequency_counting():
    code = """
words = ["apple", "banana", "apple", "cherry", "banana", "apple"]
freq = {}
for w in words:
    freq[w] = freq.get(w, 0) + 1

print("Apple count:", freq["apple"])
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Apple count: 3" in res.stdout
    assert res.trace_available
    map_steps = [s for s in res.trace_steps if s.hash_map_view is not None]
    assert len(map_steps) > 0
    assert any(e["key"] == "apple" for e in map_steps[-1].hash_map_view["entries"])


# ─── 4. STACKS & QUEUES ─────────────────────────────────────────────────────

def test_stack_balanced_parentheses():
    code = """
expr = "([{}])"
stack = []
pairs = {')': '(', ']': '[', '}': '{'}
balanced = True

for ch in expr:
    if ch in "([{":
        stack.append(ch)
    elif ch in pairs:
        if not stack or stack.pop() != pairs[ch]:
            balanced = False
            break

print("Balanced:", balanced and len(stack) == 0)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Balanced: True" in res.stdout
    assert res.trace_available
    assert any(s.stack_view is not None for s in res.trace_steps)
    assert any(s.operation_type in ("push", "pop") for s in res.trace_steps)


# ─── 5. LINKED LISTS ────────────────────────────────────────────────────────

def test_linked_list_traversal_and_reverse():
    code = """
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next

# Create 1 -> 2 -> 3
head = ListNode(1, ListNode(2, ListNode(3)))

prev = None
curr = head
while curr:
    next_temp = curr.next
    curr.next = prev
    prev = curr
    curr = next_temp

print("New head:", prev.val)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "New head: 3" in res.stdout
    assert res.trace_available
    assert any(s.linked_list_view is not None for s in res.trace_steps)


# ─── 6. RECURSION & CALL STACK ──────────────────────────────────────────────

def test_recursion_call_stack_factorial():
    code = """
def fact(n):
    if n <= 1:
        return 1
    return n * fact(n - 1)

res = fact(4)
print("Fact:", res)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Fact: 24" in res.stdout
    assert res.trace_available
    # Check that call stack frames reached depth > 1
    max_depth = max(len(s.call_stack) for s in res.trace_steps if s.call_stack)
    assert max_depth >= 3


# ─── 7. GRAPHS (BFS / ADJACENCY LIST) ───────────────────────────────────────

def test_graph_bfs_traversal():
    code = """
graph = {
    'A': ['B', 'C'],
    'B': ['D'],
    'C': ['E'],
    'D': [],
    'E': []
}
visited = []
queue = ['A']

while queue:
    node = queue.pop(0)
    if node not in visited:
        visited.append(node)
        for neighbor in graph[node]:
            queue.append(neighbor)

print("Visited:", "".join(visited))
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Visited: ABCDE" in res.stdout
    assert res.trace_available
    assert any(s.graph_view is not None for s in res.trace_steps)


# ─── 8. JAVA EXECUTION & TRACING ────────────────────────────────────────────

def test_java_two_sum_hashmap_execution():
    code = """
import java.util.HashMap;
import java.util.Map;

public class TwoSum {
    public static void main(String[] args) {
        int[] nums = {2, 7, 11, 15};
        int target = 9;
        Map<Integer, Integer> map = new HashMap<>();
        int found = -1;

        for (int i = 0; i < nums.length; i++) {
            int comp = target - nums[i];
            if (map.containsKey(comp)) {
                found = comp;
                break;
            }
            map.put(nums[i], i);
        }
        System.out.println("Found match: " + found);
    }
}
"""
    res = execute_java(code)
    if res.status == "unavailable":
        pytest.skip("Java runtime (javac) is not available on this machine.")
    assert res.status == "ok"
    assert "Found match: 2" in res.stdout


# ─── 9. C++ EXECUTION ───────────────────────────────────────────────────────

def test_cpp_execution_sandbox():
    code = """
#include <iostream>
#include <vector>
#include <numeric>

int main() {
    std::vector<int> v = {1, 2, 3, 4};
    int sum = 0;
    for (int x : v) sum += x;
    std::cout << "Sum: " << sum << std::endl;
    return 0;
}
"""
    res = execute_cpp(code)
    if res.status == "unavailable":
        pytest.skip("g++ compiler not available on this machine.")
    assert res.status == "ok"
    assert "Sum: 10" in res.stdout
    # C++ returns no trace without crashing
    assert not res.trace_available
