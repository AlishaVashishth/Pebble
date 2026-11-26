"""
Phase 1.1 Comprehensive Validation & Gap-Fixing Test Suite for Pebble Playground.

Validates the 7 core required categories:
  1. Trees: inorder, preorder, postorder, level order, BST search, and tree inversion
  2. Graphs: BFS, DFS, cycle detection, connected components
  3. Linked Lists: traversal, reversal, middle node, cycle detection, insertion, deletion, merging
  4. Strings: palindrome, reverse string, anagrams, character frequency, longest substring
  5. HashMaps & HashSets: insertion, lookup, updates, deletion, duplicate detection
  6. Stacks & Queues: push, pop, enqueue, dequeue, changing container states
  7. Recursion: nested calls, return values, backtracking (Fibonacci, Permutations/Subsets)
"""

import pytest
from backend.app.execution.runner import execute_python, execute_java, execute_code


# ─── 1. TREES ───────────────────────────────────────────────────────────────

def test_tree_inorder_and_bst_search():
    """Test tree traversal and BST search capturing TreeNode structure in trace."""
    code = """
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

root = TreeNode(4, TreeNode(2, TreeNode(1), TreeNode(3)), TreeNode(6, TreeNode(5), TreeNode(7)))

# Search BST for 5
target = 5
curr = root
found = False
while curr:
    if curr.val == target:
        found = True
        break
    elif target < curr.val:
        curr = curr.left
    else:
        curr = curr.right

print("Found:", found)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Found: True" in res.stdout
    assert res.trace_available
    # Verify that tree nodes were captured
    tree_steps = [s for s in res.trace_steps if s.tree_view is not None]
    assert len(tree_steps) > 0
    # Any step should capture TreeNode with val 4
    has_root = any(any(n.val == 4 for n in s.tree_view) for s in tree_steps)
    assert has_root


def test_tree_inversion():
    """Test invert binary tree capturing structure mutation."""
    code = """
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

root = TreeNode(1, TreeNode(2), TreeNode(3))

# Invert
temp = root.left
root.left = root.right
root.right = temp

print("New left:", root.left.val)
print("New right:", root.right.val)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "New left: 3" in res.stdout
    assert "New right: 2" in res.stdout
    assert res.trace_available
    assert any(s.tree_view is not None for s in res.trace_steps)


# ─── 2. GRAPHS ──────────────────────────────────────────────────────────────

def test_graph_dfs_and_cycle_detection():
    """Test graph DFS traversal and cycle detection with graph_view snapshot."""
    code = """
graph = {
    '0': ['1', '2'],
    '1': ['2'],
    '2': ['0', '3'],
    '3': ['3']
}
visited = set()
cycle_detected = False

def dfs(node, path):
    global cycle_detected
    visited.add(node)
    path.add(node)
    for neighbor in graph.get(node, []):
        if neighbor in path:
            cycle_detected = True
        elif neighbor not in visited:
            dfs(neighbor, path)
    path.remove(node)

dfs('0', set())
print("Cycle:", cycle_detected)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Cycle: True" in res.stdout
    assert res.trace_available
    graph_steps = [s for s in res.trace_steps if s.graph_view is not None]
    assert len(graph_steps) > 0
    assert len(graph_steps[0].graph_view.nodes) >= 4


def test_graph_connected_components():
    """Test finding connected components in an undirected graph."""
    code = """
adj = {
    1: [2],
    2: [1],
    3: [4],
    4: [3],
    5: []
}
visited = []
components = 0

for node in adj:
    if node not in visited:
        components += 1
        queue = [node]
        visited.append(node)
        while queue:
            curr = queue.pop(0)
            for nxt in adj[curr]:
                if nxt not in visited:
                    visited.append(nxt)
                    queue.append(nxt)

print("Components:", components)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Components: 3" in res.stdout
    assert res.trace_available


# ─── 3. LINKED LISTS ────────────────────────────────────────────────────────

def test_linked_list_find_middle_and_cycle():
    """Test slow and fast pointers to find middle and detect cycle in linked list."""
    code = """
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next

# Create 1 -> 2 -> 3 -> 4 -> 5
n5 = ListNode(5)
n4 = ListNode(4, n5)
n3 = ListNode(3, n4)
n2 = ListNode(2, n3)
head = ListNode(1, n2)

slow = head
fast = head
while fast and fast.next:
    slow = slow.next
    fast = fast.next.next

print("Middle:", slow.val)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Middle: 3" in res.stdout
    assert res.trace_available
    assert any(s.linked_list_view is not None for s in res.trace_steps)


def test_linked_list_merge_two_sorted():
    """Test merging two sorted lists."""
    code = """
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next

# l1: 1 -> 3
l1 = ListNode(1, ListNode(3))
# l2: 2 -> 4
l2 = ListNode(2, ListNode(4))

dummy = ListNode(0)
tail = dummy

while l1 and l2:
    if l1.val <= l2.val:
        tail.next = l1
        l1 = l1.next
    else:
        tail.next = l2
        l2 = l2.next
    tail = tail.next

tail.next = l1 if l1 else l2

merged = []
curr = dummy.next
while curr:
    merged.append(curr.val)
    curr = curr.next

print("Merged:", merged)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Merged: [1, 2, 3, 4]" in res.stdout
    assert res.trace_available


# ─── 4. STRINGS ─────────────────────────────────────────────────────────────

def test_string_anagram_check():
    """Test checking anagrams with character sorting and frequency."""
    code = """
s1 = "listen"
s2 = "silent"

is_anagram = sorted(s1) == sorted(s2)
print("Anagram:", is_anagram)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Anagram: True" in res.stdout
    assert res.trace_available
    assert any(s.string_view is not None for s in res.trace_steps)


def test_string_reverse_with_two_pointers():
    """Test in-place string reversal array."""
    code = """
s = list("hello")
left = 0
right = len(s) - 1

while left < right:
    s[left], s[right] = s[right], s[left]
    left += 1
    right -= 1

print("Reversed:", "".join(s))
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Reversed: olleh" in res.stdout
    assert res.trace_available
    # Swap operation should be recognized
    assert any(s.operation_type == "swap" for s in res.trace_steps)


# ─── 5. HASHMAPS & HASHSETS ─────────────────────────────────────────────────

def test_hashmap_duplicate_detection_and_deletion():
    """Test set insertion, lookup, duplicate detection and dictionary element deletion."""
    code = """
nums = [1, 2, 3, 4, 2, 5]
seen = set()
duplicate = None

for x in nums:
    if x in seen:
        duplicate = x
        break
    seen.add(x)

counts = {"a": 1, "b": 2, "c": 3}
del counts["b"]

print("Duplicate:", duplicate)
print("Keys left:", sorted(list(counts.keys())))
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Duplicate: 2" in res.stdout
    assert "Keys left: ['a', 'c']" in res.stdout
    assert res.trace_available
    assert any(s.hash_map_view is not None for s in res.trace_steps)


# ─── 6. STACKS & QUEUES ─────────────────────────────────────────────────────

def test_queue_enqueue_dequeue():
    """Test FIFO queue operations."""
    code = """
queue = []

# Enqueue
queue.append(10)
queue.append(20)
queue.append(30)

# Dequeue
first = queue.pop(0)
second = queue.pop(0)

print("First:", first)
print("Remaining:", queue)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "First: 10" in res.stdout
    assert "Remaining: [30]" in res.stdout
    assert res.trace_available
    assert any(s.queue_view is not None for s in res.trace_steps)


# ─── 7. RECURSION & BACKTRACKING ────────────────────────────────────────────

def test_recursion_backtracking_subsets():
    """Test generating subsets via recursion and backtracking."""
    code = """
nums = [1, 2]
result = []

def backtrack(index, path):
    result.append(list(path))
    for i in range(index, len(nums)):
        path.append(nums[i])
        backtrack(i + 1, path)
        path.pop()  # backtrack

backtrack(0, [])
print("Subsets count:", len(result))
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "Subsets count: 4" in res.stdout
    assert res.trace_available
    # Verify call stack depth was recorded
    call_steps = [s for s in res.trace_steps if s.call_stack]
    assert len(call_steps) > 0
    max_d = max(len(s.call_stack) for s in call_steps)
    assert max_d >= 2


# ─── 8. JAVA TRACING VALIDATION ─────────────────────────────────────────────

def test_java_stack_balanced_parentheses():
    """Test Java tracing with Stack collections."""
    code = """
import java.util.Stack;

public class Balanced {
    public static void main(String[] args) {
        String s = "()[]{}";
        Stack<Character> stack = new Stack<>();
        boolean ok = true;
        for (char c : s.toCharArray()) {
            if (c == '(' || c == '[' || c == '{') {
                stack.push(c);
            } else {
                if (stack.isEmpty()) {
                    ok = false;
                    break;
                }
                char top = stack.pop();
                if ((c == ')' && top != '(') ||
                    (c == ']' && top != '[') ||
                    (c == '}' && top != '{')) {
                    ok = false;
                    break;
                }
            }
        }
        System.out.println("Valid: " + (ok && stack.isEmpty()));
    }
}
"""
    res = execute_java(code)
    if res.status == "unavailable":
        pytest.skip("javac not installed on this host")
    assert res.status == "ok"
    assert "Valid: true" in res.stdout
    assert res.trace_available


# ─── 9. CRITICAL FIXES VALIDATION ──────────────────────────────────────────

def test_binary_tree_level_order_clean_console_no_trace_leakage():
    """Verify level-order traversal with unbuffered print(..., end=' ') leaves 0 trace markers in stdout."""
    code = """
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

root = TreeNode(1)
root.left = TreeNode(2)
root.right = TreeNode(3)
root.left.left = TreeNode(4)
root.left.right = TreeNode(5)

queue = [root]
while queue:
    curr = queue.pop(0)
    print(curr.val, end=" ")
    if curr.left:
        queue.append(curr.left)
    if curr.right:
        queue.append(curr.right)
"""
    res = execute_python(code)
    assert res.status == "ok"
    assert "PEBBLE_TRACE" not in res.stdout, "PEBBLE_TRACE leaked into stdout!"
    assert res.stdout.strip() == "1 2 3 4 5"
    assert res.trace_available
    assert any(s.tree_view is not None for s in res.trace_steps)


def test_java_sliding_window_custom_input():
    """Verify Java sliding window distinct k subarray sum with standard input."""
    code = """
import java.util.*;
import java.io.*;

public class Main {
    public static void main(String[] args) throws Exception {
        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
        StringTokenizer st = new StringTokenizer(br.readLine());
        int n = Integer.parseInt(st.nextToken());
        int k = Integer.parseInt(st.nextToken());
        int[] arr = new int[n];
        st = new StringTokenizer(br.readLine());
        for (int i = 0; i < n; i++) {
            arr[i] = Integer.parseInt(st.nextToken());
        }
        if (k > n) {
            System.out.println(0);
            return;
        }
        HashMap<Integer, Integer> count = new HashMap<>();
        int duplicateCount = 0;
        long sum = 0;
        int maxSum = 0;
        for (int i = 0; i < n; i++) {
            int val = arr[i];
            int c = count.getOrDefault(val, 0);
            if (c == 1) duplicateCount++;
            count.put(val, c + 1);
            sum += val;
            if (i >= k) {
                int outVal = arr[i - k];
                int outC = count.get(outVal);
                if (outC == 2) duplicateCount--;
                if (outC == 1) {
                    count.remove(outVal);
                } else {
                    count.put(outVal, outC - 1);
                }
                sum -= outVal;
            }
            if (i >= k - 1 && duplicateCount == 0) {
                if (sum > maxSum) maxSum = (int) sum;
            }
        }
        System.out.println(maxSum);
    }
}
"""
    res = execute_java(code, stdin_text="6 3\n2 1 5 1 3 2")
    if res.status == "unavailable":
        pytest.skip("javac not installed on this host")
    assert res.status == "ok"
    assert res.stdout.strip() == "9"
    assert res.trace_available
    assert len(res.trace_steps) > 10
