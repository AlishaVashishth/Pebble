/**
 * Playground API client and type definitions.
 * Reuses the existing `request` utility from api.ts — no duplicate fetch logic.
 */

import { request } from './api.ts';

export type PlaygroundMode = 'explain' | 'solve';
export type PlaygroundLanguage = 'python' | 'java' | 'cpp';

export interface PlaygroundRequest {
  mode: PlaygroundMode;
  language: PlaygroundLanguage;
  code?: string;
  problem?: string;
  custom_input?: string;
}

export interface PlaygroundResponse {
  status: 'ok' | 'error';
  mode: PlaygroundMode;
  language: PlaygroundLanguage;
  solution_code: string;
  explanation: string;
  approach: string;
  source: 'db' | 'llm' | 'passthrough';
  error?: string;
}

export interface CallStackFrame {
  func_name: string;
  args: Record<string, unknown>;
  return_value?: unknown;
  depth: number;
  frame_id?: string;
  parent_frame_id?: string;
  local_vars?: Record<string, unknown>;
  line_number?: number;
  status?: 'active' | 'returning';
}

export interface LinkedListNode {
  id: string;
  val: unknown;
  next_id?: string | null;
}

export interface TreeNode {
  id: string;
  val: unknown;
  left_id?: string | null;
  right_id?: string | null;
}

export interface GraphData {
  nodes: Array<{ id: string; label?: string; [key: string]: unknown }>;
  edges: Array<{ source: string; target: string; [key: string]: unknown }>;
  visited: string[];
  current_node?: string | null;
}

export interface TraceStep {
  step: number;
  line_number: number;
  local_vars: Record<string, unknown>;
  description: string;
  pointers?: Record<string, number>;
  active_array?: string | null;
  window?: [number, number] | null;
  accessed_indices?: number[];
  operation_type?: string;
  explanation?: string;
  changed_vars?: string[];

  // Universal DSA Structure Enriched Fields
  data_structure_type?: 'array' | 'string' | 'hashmap' | 'set' | 'stack' | 'queue' | 'linked_list' | 'tree' | 'graph' | 'recursion';
  string_view?: {
    text: string;
    chars: string[];
    pointers?: Record<string, number>;
    window?: [number, number] | null;
  };
  hash_map_view?: {
    entries: Array<{ key: string; value: unknown; was_updated?: boolean }>;
    size: number;
  };
  stack_view?: unknown[];
  queue_view?: unknown[];
  linked_list_view?: LinkedListNode[];
  tree_view?: TreeNode[];
  call_stack?: CallStackFrame[];
  call_depth?: number;
  event_type?: string;
  return_value?: unknown;
  graph_view?: GraphData;
}

export interface PlaygroundPreset {
  id: string;
  title: string;
  category: string;
  language: PlaygroundLanguage;
  code: string;
  javaCode?: string;
  custom_input: string;
  description: string;
}

export const PLAYGROUND_PRESETS: PlaygroundPreset[] = [
  {
    id: 'sliding-window',
    title: 'Sliding Window',
    category: 'Array / Window',
    language: 'python',
    code: `arr = [2, 3, 1, 2, 4, 3]
target = 7

left = 0
window_sum = 0
best_length = float('inf')

for right in range(len(arr)):
    window_sum += arr[right]
    while window_sum >= target:
        best_length = min(best_length, right - left + 1)
        window_sum -= arr[left]
        left += 1

result = 0 if best_length == float('inf') else best_length
print("Smallest window length:", result)`,
    javaCode: `public class SlidingWindow {
    public static void main(String[] args) {
        int[] arr = {2, 3, 1, 2, 4, 3};
        int target = 7;
        int left = 0;
        int window_sum = 0;
        int best_length = Integer.MAX_VALUE;

        for (int right = 0; right < arr.length; right++) {
            window_sum += arr[right];
            while (window_sum >= target) {
                best_length = Math.min(best_length, right - left + 1);
                window_sum -= arr[left];
                left++;
            }
        }
        System.out.println("Smallest window length: " + (best_length == Integer.MAX_VALUE ? 0 : best_length));
    }
}`,
    custom_input: '',
    description: 'Find minimal subarray length summing to at least target',
  },
  {
    id: 'two-pointers',
    title: 'Two Pointers (Two Sum)',
    category: 'Two Pointers',
    language: 'python',
    code: `nums = [2, 7, 11, 15]
target = 9

left = 0
right = len(nums) - 1
found = False

while left < right:
    curr_sum = nums[left] + nums[right]
    if curr_sum == target:
        found = True
        break
    elif curr_sum < target:
        left += 1
    else:
        right -= 1

print(f"Indices: [{left}, {right}], found: {found}")`,
    javaCode: `public class TwoSum {
    public static void main(String[] args) {
        int[] nums = {2, 7, 11, 15};
        int target = 9;
        int left = 0;
        int right = nums.length - 1;
        boolean found = false;

        while (left < right) {
            int curr_sum = nums[left] + nums[right];
            if (curr_sum == target) {
                found = true;
                break;
            } else if (curr_sum < target) {
                left++;
            } else {
                right--;
            }
        }
        System.out.println("Indices: [" + left + ", " + right + "], found: " + found);
    }
}`,
    custom_input: '',
    description: 'Two pointers on sorted array converging towards target sum',
  },
  {
    id: 'binary-search',
    title: 'Binary Search',
    category: 'Searching',
    language: 'python',
    code: `arr = [1, 3, 5, 7, 9, 11, 13, 15]
target = 7

low = 0
high = len(arr) - 1
ans = -1

while low <= high:
    mid = (low + high) // 2
    if arr[mid] == target:
        ans = mid
        break
    elif arr[mid] < target:
        low = mid + 1
    else:
        high = mid - 1

print("Found at index:", ans)`,
    javaCode: `public class BinarySearch {
    public static void main(String[] args) {
        int[] arr = {1, 3, 5, 7, 9, 11, 13, 15};
        int target = 7;
        int low = 0;
        int high = arr.length - 1;
        int ans = -1;

        while (low <= high) {
            int mid = (low + high) / 2;
            if (arr[mid] == target) {
                ans = mid;
                break;
            } else if (arr[mid] < target) {
                low = mid + 1;
            } else {
                high = mid - 1;
            }
        }
        System.out.println("Found at index: " + ans);
    }
}`,
    custom_input: '',
    description: 'Halve the search space repeatedly with low, mid, and high',
  },
  {
    id: 'bubble-sort',
    title: 'Bubble Sort',
    category: 'Sorting',
    language: 'python',
    code: `arr = [5, 2, 8, 1, 3]
n = len(arr)

for i in range(n):
    for j in range(0, n - i - 1):
        if arr[j] > arr[j + 1]:
            arr[j], arr[j + 1] = arr[j + 1], arr[j]

print("Sorted array:", arr)`,
    javaCode: `public class BubbleSort {
    public static void main(String[] args) {
        int[] arr = {5, 2, 8, 1, 3};
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
        System.out.println("Sorted array: " + java.util.Arrays.toString(arr));
    }
}`,
    custom_input: '',
    description: 'Compare adjacent pairs and bubble the largest element to the end',
  },
];

export interface ExecuteRequest {
  language: PlaygroundLanguage;
  code: string;
  custom_input?: string;
  timeout_seconds?: number;
}

export interface ExecuteResponse {
  status: 'ok' | 'error' | 'timeout' | 'compile_error' | 'unavailable';
  stdout: string;
  stderr: string;
  exit_code: number;
  execution_time_ms: number;
  timed_out: boolean;
  trace_steps: TraceStep[];
  trace_available: boolean;
  language: string;
  language_unavailable: boolean;
}

/** POST /playground — submit code/problem to the backend */
export function submitPlayground(
  payload: PlaygroundRequest,
  signal?: AbortSignal
): Promise<PlaygroundResponse> {
  return request<PlaygroundResponse>('/playground', {
    method: 'POST',
    body: payload,
    auth: true,
    signal,
  });
}

/** POST /playground/execute — execute code in isolated sandbox */
export function executeCode(
  payload: ExecuteRequest,
  signal?: AbortSignal
): Promise<ExecuteResponse> {
  return request<ExecuteResponse>('/playground/execute', {
    method: 'POST',
    body: payload,
    auth: true,
    signal,
  });
}

// ─── Local persistence ────────────────────────────────────────────────────────

const STORAGE_KEY = 'pebble_playground_draft';

export interface PlaygroundDraft {
  mode: PlaygroundMode;
  language: PlaygroundLanguage;
  code: string;
  problem: string;
  customInput: string;
}

export function loadPlaygroundDraft(): PlaygroundDraft {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as PlaygroundDraft;
  } catch {
    // ignore
  }
  return { mode: 'explain', language: 'python', code: '', problem: '', customInput: '' };
}

export function savePlaygroundDraft(draft: PlaygroundDraft): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
  } catch {
    // ignore
  }
}

