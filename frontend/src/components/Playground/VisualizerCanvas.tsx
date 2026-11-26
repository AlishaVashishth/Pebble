/**
 * VisualizerCanvas — Pebble Playground 2.0 Universal Visual Execution & Dry-Run Canvas.
 *
 * Supports comprehensive data structure visual stages:
 *  - 1. Strings: Character-by-character stage with left/right pointers, substring window, comparisons
 *  - 2. Arrays: Animated array stage, pointers (top/bottom), swaps, comparisons, sorted tails
 *  - 3. HashMaps / Sets: Key-value entry cards with update/insertion pulse badges
 *  - 4. Stacks & Queues: Interactive container showing push/pop, top element, front/rear
 *  - 5. Linked Lists: Sequential node blocks with pointers and next connections
 *  - 6. Binary Trees: Visual hierarchical nodes with left/right links and current target
 *  - 7. Recursion / Call Stack: Live stack frame breakdown with depth, arguments, and return values
 *  - 8. Graphs: Visited list, active node exploration, adjacency connections
 *  - 9. Variable Inspector: Stat cards with change indicators
 *  - 10. Contextual Explanation callout: Plain-English algorithm step reasoning
 *  - 11. Dry-Run History Table: Interactive step jumping with auto-scrolling
 *  - 12. Program Console: Real stdout, stderr, exit code, execution time
 */

import React, { useMemo, useRef, useEffect } from 'react';
import {
  Code2,
  Terminal,
  Clock,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Boxes,
  Sparkles,
  TableProperties,
  ArrowRight,
  Database,
  Layers,
  GitBranch,
  Network,
  AlignLeft,
} from 'lucide-react';
import { ExecuteResponse, TraceStep } from '../../lib/playground.ts';

interface VisualizerCanvasProps {
  code: string;
  executionResult: ExecuteResponse | null;
  currentStep: TraceStep | null;
  currentStepIndex: number;
  totalSteps: number;
  allSteps: TraceStep[];
  language: string;
  onJumpToStep: (index: number) => void;
}

export const VisualizerCanvas: React.FC<VisualizerCanvasProps> = ({
  code,
  executionResult,
  currentStep,
  currentStepIndex,
  totalSteps,
  allSteps,
  language,
  onJumpToStep,
}) => {
  const tableRef = useRef<HTMLDivElement>(null);
  const activeRowRef = useRef<HTMLTableRowElement>(null);

  // Auto-scroll active history table row into view
  useEffect(() => {
    if (activeRowRef.current && tableRef.current) {
      activeRowRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest',
      });
    }
  }, [currentStepIndex]);

  // Separate array variables vs primitive variables
  const { arrayVars, primitiveVars, primaryArrayName, primaryArray } = useMemo(() => {
    let effectiveStep = currentStep;
    if (
      effectiveStep &&
      effectiveStep.local_vars &&
      Object.keys(effectiveStep.local_vars).length === 0 &&
      allSteps.length > 1
    ) {
      for (let look = currentStepIndex + 1; look < Math.min(currentStepIndex + 5, allSteps.length); look++) {
        const candidate = allSteps[look];
        if (candidate?.local_vars && Object.keys(candidate.local_vars).length > 0) {
          effectiveStep = candidate;
          break;
        }
      }
    }

    if (!effectiveStep || !effectiveStep.local_vars) {
      return { arrayVars: {}, primitiveVars: {}, primaryArrayName: null, primaryArray: [] };
    }
    const arrays: Record<string, unknown[]> = {};
    const primitives: Record<string, unknown> = {};

    for (const [key, val] of Object.entries(effectiveStep.local_vars)) {
      if (Array.isArray(val)) {
        arrays[key] = val;
      } else if (typeof val !== 'object' || val === null) {
        if (typeof val === 'string' && (val.startsWith('<function ') || val.startsWith('<class ') || val.startsWith('<module '))) {
          continue;
        }
        primitives[key] = val;
      }
    }

    let pName = effectiveStep.active_array || null;
    if (!pName || !arrays[pName]) {
      const keys = Object.keys(arrays);
      pName = keys.length > 0 ? keys[0] : null;
    }
    const pArray = pName ? arrays[pName] : [];

    return {
      arrayVars: arrays,
      primitiveVars: primitives,
      primaryArrayName: pName,
      primaryArray: pArray,
    };
  }, [currentStep, currentStepIndex, allSteps]);

  // Collect columns for history table
  const historyColumns = useMemo(() => {
    const keys = new Set<string>();
    for (const s of allSteps.slice(0, 30)) {
      if (s.local_vars) {
        for (const [k, v] of Object.entries(s.local_vars)) {
          if (!Array.isArray(v) && (typeof v !== 'object' || v === null)) {
            if (typeof v === 'string' && (v.startsWith('<function ') || v.startsWith('<class ') || v.startsWith('<module '))) {
              continue;
            }
            keys.add(k);
          }
        }
      }
    }
    return Array.from(keys).slice(0, 6);
  }, [allSteps]);

  // Pointer labels on top vs bottom of array cells
  const { topPointers, bottomPointers } = useMemo(() => {
    const top: Record<number, string[]> = {};
    const bottom: Record<number, string[]> = {};

    if (currentStep?.pointers) {
      for (const [name, idx] of Object.entries(currentStep.pointers)) {
        if (typeof idx === 'number' && idx >= 0) {
          const lower = name.toLowerCase();
          if (['left', 'low', 'i', 'start', 'slow', 'first', 'l', 'front'].includes(lower)) {
            if (!top[idx]) top[idx] = [];
            top[idx].push(name);
          } else {
            if (!bottom[idx]) bottom[idx] = [];
            bottom[idx].push(name);
          }
        }
      }
    }
    return { topPointers: top, bottomPointers: bottom };
  }, [currentStep]);

  // Group tree nodes into visual hierarchy levels (BFS from root)
  const treeLevels = useMemo(() => {
    if (!currentStep?.tree_view || currentStep.tree_view.length === 0) return [];
    const nodes = currentStep.tree_view;
    const nodeMap = new Map<string, any>();
    const childIds = new Set<string>();

    nodes.forEach((n) => {
      nodeMap.set(String(n.id), n);
      if (n.left_id) childIds.add(String(n.left_id));
      if (n.right_id) childIds.add(String(n.right_id));
    });

    const roots = nodes.filter((n) => !childIds.has(String(n.id)));
    const rootNode = roots.length > 0 ? roots[0] : nodes[0];

    const levelsMap: Map<number, any[]> = new Map();
    const visited = new Set<string>();
    const q: { node: any; depth: number }[] = [{ node: rootNode, depth: 0 }];
    visited.add(String(rootNode.id));

    while (q.length > 0) {
      const { node, depth } = q.shift()!;
      if (!levelsMap.has(depth)) levelsMap.set(depth, []);
      levelsMap.get(depth)!.push(node);

      if (node.left_id && nodeMap.has(String(node.left_id)) && !visited.has(String(node.left_id))) {
        visited.add(String(node.left_id));
        q.push({ node: nodeMap.get(String(node.left_id))!, depth: depth + 1 });
      }
      if (node.right_id && nodeMap.has(String(node.right_id)) && !visited.has(String(node.right_id))) {
        visited.add(String(node.right_id));
        q.push({ node: nodeMap.get(String(node.right_id))!, depth: depth + 1 });
      }
    }

    nodes.forEach((n) => {
      if (!visited.has(String(n.id))) {
        const maxDepth = Math.max(...Array.from(levelsMap.keys()), 0) + 1;
        if (!levelsMap.has(maxDepth)) levelsMap.set(maxDepth, []);
        levelsMap.get(maxDepth)!.push(n);
      }
    });

    return Array.from(levelsMap.entries()).sort(([a], [b]) => a - b);
  }, [currentStep?.tree_view]);

  if (!executionResult) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-4 text-center space-y-3">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[#6C5CFF]/10 to-[#3CC8FF]/10 text-[#6C5CFF] flex items-center justify-center shadow-xs border border-[#6C5CFF]/20">
          <Code2 className="w-7 h-7 stroke-[1.75]" />
        </div>
        <div className="space-y-1.5">
          <p className="text-base font-semibold text-[#111113]">Visual Execution Canvas Ready</p>
          <p className="text-xs text-[#8A8A90] max-w-md mx-auto leading-relaxed">
            Choose an algorithm preset or enter your code, set optional input, and click{' '}
            <strong className="text-[#111113]">Run & Trace</strong> to watch step-by-step array animations,
            pointer movements, and variable dry-run logs.
          </p>
        </div>
      </div>
    );
  }

  const {
    status,
    stdout,
    stderr,
    exit_code,
    execution_time_ms,
    trace_available,
  } = executionResult;

  const isOk = status === 'ok';
  const isTimeout = status === 'timeout';
  const isCompileError = status === 'compile_error';
  const isRuntimeError = status === 'error';

  const windowRange = currentStep?.window || null;
  const changedVars = currentStep?.changed_vars || [];

  // Helper to format values for Stack / Queue elements (handles TreeNode objects cleanly)
  const formatQueueStackItem = (item: any): string => {
    if (item === null || item === undefined) return 'null';
    if (typeof item === 'object') {
      if ('val' in item) return String(item.val);
      if ('value' in item) return String(item.value);
      if ('data' in item) return String(item.data);
      if ('node_id' in item) return `Node(${String(item.node_id).slice(-4)})`;
      return JSON.stringify(item);
    }
    return String(item);
  };

  // Check if a tree node is currently being visited/processed
  const isTreeNodeActive = (node: any): boolean => {
    if (!currentStep) return false;
    const lVars = currentStep.local_vars || {};
    for (const [key, val] of Object.entries(lVars)) {
      if (val === null || val === undefined) continue;
      if (typeof val === 'object') {
        if ((val as any).node_id && String((val as any).node_id) === String(node.id)) return true;
        if ((val as any).id && String((val as any).id) === String(node.id)) return true;
        if ('val' in (val as any) && String((val as any).val) === String(node.val)) {
          if (['curr', 'node', 'current', 'root', 'target', 'p', 'q'].includes(key.toLowerCase())) {
            return true;
          }
        }
      } else {
        if (['val', 'curr', 'node', 'target', 'x'].includes(key.toLowerCase()) && String(val) === String(node.val)) {
          return true;
        }
      }
    }
    return false;
  };

  return (
    <div className="space-y-6 p-5">
      {/* ── Status Banner ── */}
      <div
        className={`flex items-center justify-between px-4 py-2.5 rounded-2xl border text-xs font-medium ${
          isOk
            ? 'bg-emerald-50/80 border-emerald-200/80 text-emerald-800'
            : isTimeout
            ? 'bg-amber-50/80 border-amber-200/80 text-amber-800'
            : isCompileError
            ? 'bg-rose-50/80 border-rose-200/80 text-rose-800'
            : isRuntimeError
            ? 'bg-red-50/80 border-red-200/80 text-red-800'
            : 'bg-zinc-50 border-zinc-200 text-zinc-700'
        }`}
      >
        <div className="flex items-center gap-2">
          {isOk ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
          ) : isTimeout ? (
            <Clock className="w-4 h-4 text-amber-600 shrink-0" />
          ) : (
            <XCircle className="w-4 h-4 text-rose-600 shrink-0" />
          )}
          <span>
            {isOk
              ? 'Execution Completed'
              : isTimeout
              ? 'Execution Timed Out'
              : isCompileError
              ? 'Compilation Error'
              : isRuntimeError
              ? 'Runtime Error'
              : 'Runtime Unavailable'}
          </span>
        </div>

        <div className="flex items-center gap-3 font-mono text-[11px] opacity-80">
          <span>{execution_time_ms.toFixed(1)} ms</span>
          <span>•</span>
          <span>exit code {exit_code}</span>
        </div>
      </div>

      {/* ── Unsupported Trace Notice (e.g. C++) ── */}
      {!trace_available && isOk && (
        <div className="flex items-start gap-2.5 p-4 bg-blue-50/70 border border-blue-200/60 rounded-2xl text-xs text-blue-900 leading-relaxed shadow-2xs">
          <HelpCircle className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold">{language.toUpperCase()} executed successfully in the sandbox.</span>{' '}
            Program output is displayed in the console below. Interactive step-by-step visual tracing is supported for Python and Java.
          </div>
        </div>
      )}

      {/* ── Active Visual Execution Section (Trace Ready) ── */}
      {trace_available && currentStep && (
        <div className="space-y-5">
          {/* 1. STRING VISUALIZER STAGE */}
          {currentStep.string_view && currentStep.string_view.chars && currentStep.string_view.chars.length > 0 && (
            <div className="bg-white rounded-2xl border border-black/[0.06] p-4 shadow-sm space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold text-[#44444C]">
                <div className="flex items-center gap-2 uppercase tracking-wider">
                  <AlignLeft className="w-3.5 h-3.5 text-[#6C5CFF]" />
                  <span>String Stage: <code className="font-mono text-[#111113] lowercase">"{currentStep.string_view.text}"</code></span>
                </div>
                {currentStep.string_view.window && (
                  <span className="text-[11px] font-mono text-[#6C5CFF] bg-[#6C5CFF]/10 px-2 py-0.5 rounded-md">
                    Substring Window: [{currentStep.string_view.window[0]}..{currentStep.string_view.window[1]}]
                  </span>
                )}
              </div>

              <div className="overflow-x-auto py-2">
                <div className="flex items-center gap-2 min-w-min px-1 py-1">
                  {currentStep.string_view.chars.map((char, idx) => {
                    const topTags = topPointers[idx] || [];
                    const bottomTags = bottomPointers[idx] || [];
                    const inWindow = currentStep.string_view?.window &&
                      idx >= currentStep.string_view.window[0] &&
                      idx <= currentStep.string_view.window[1];
                    const isAccessed = currentStep.accessed_indices?.includes(idx);

                    return (
                      <div key={idx} className="flex flex-col items-center shrink-0 w-12 select-none">
                        <div className="h-5 flex items-end justify-center text-[10px] font-bold font-mono text-[#3B5BDB] pb-0.5">
                          {topTags.length > 0 && (
                            <span className="bg-[#EEF2FF] text-[#3B5BDB] px-1 rounded border border-[#C7D2FE]">
                              {topTags.join(',')}
                            </span>
                          )}
                        </div>
                        <div
                          className={`w-12 h-12 rounded-xl flex items-center justify-center font-mono text-base font-bold transition-all border-2 ${
                            inWindow
                              ? 'bg-[#FFD166] text-[#4A3500] border-[#FFB703] shadow-md scale-105'
                              : isAccessed
                              ? 'bg-[#EEF2FF] text-[#3B5BDB] border-[#3B5BDB] shadow-sm'
                              : 'bg-[#F8F9FA] text-[#1F2937] border-black/[0.08]'
                          }`}
                        >
                          '{char}'
                        </div>
                        <span className="text-[10px] font-mono text-[#8A8A90] mt-1">{idx}</span>
                        <div className="h-5 flex items-start justify-center text-[10px] font-bold font-mono text-[#B33CF0] pt-0.5">
                          {bottomTags.length > 0 && (
                            <span className="bg-[#FAF5FF] text-[#B33CF0] px-1 rounded border border-[#E9D5FF]">
                              {bottomTags.join(',')}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* 2. ARRAY STAGE & POINTER CANVAS */}
          {primaryArray && primaryArray.length > 0 && (
            <div className="bg-white rounded-2xl border border-black/[0.06] p-4 shadow-sm space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold text-[#44444C]">
                <div className="flex items-center gap-2 uppercase tracking-wider">
                  <Boxes className="w-3.5 h-3.5 text-[#6C5CFF]" />
                  <span>Array Stage: <code className="font-mono text-[#111113] lowercase">{primaryArrayName}</code></span>
                </div>
                <div className="flex items-center gap-2">
                  {currentStep.operation_type === 'swap' && (
                    <span className="text-[10px] font-bold uppercase tracking-wider text-purple-700 bg-purple-100 px-2 py-0.5 rounded-md border border-purple-200 animate-pulse">
                      Swap
                    </span>
                  )}
                  {currentStep.operation_type === 'compare' && (
                    <span className="text-[10px] font-bold uppercase tracking-wider text-amber-700 bg-amber-100 px-2 py-0.5 rounded-md border border-amber-200">
                      Comparing
                    </span>
                  )}
                  {windowRange && (
                    <span className="text-[11px] font-mono text-[#6C5CFF] bg-[#6C5CFF]/10 px-2 py-0.5 rounded-md">
                      Active Window: [{windowRange[0]}..{windowRange[1]}]
                    </span>
                  )}
                </div>
              </div>

              {/* Horizontal Scrollable Stage */}
              <div className="overflow-x-auto py-2">
                <div className="flex items-center gap-2.5 min-w-min px-1 py-1">
                  {primaryArray.map((val, idx) => {
                    const topTags = topPointers[idx] || [];
                    const bottomTags = bottomPointers[idx] || [];
                    const inWindow =
                      windowRange !== null &&
                      idx >= windowRange[0] &&
                      idx <= windowRange[1];
                    const isAccessed = currentStep.accessed_indices?.includes(idx);
                    const isSwapOp = currentStep.operation_type === 'swap' && isAccessed;
                    const isCompareOp = (currentStep.operation_type === 'compare' || (!isSwapOp && currentStep.accessed_indices && currentStep.accessed_indices.length >= 2)) && isAccessed;

                    const nVal = Number(primitiveVars.n || primitiveVars.len || primitiveVars.size);
                    const iVal = Number(primitiveVars.i);
                    const isSortedTail = Number.isFinite(nVal) && Number.isFinite(iVal) && nVal > 0 && iVal >= 0 && idx >= nVal - iVal;
                    const isAllSorted = currentStepIndex === totalSteps - 1 && isOk;
                    const isSorted = isSortedTail || isAllSorted;

                    return (
                      <div key={idx} className="flex flex-col items-center shrink-0 w-14 select-none">
                        <div className="h-6 flex items-end justify-center text-[11px] font-bold font-mono text-[#3B5BDB] pb-0.5">
                          {topTags.length > 0 && (
                            <span className="bg-[#EEF2FF] text-[#3B5BDB] px-1.5 py-0.2 rounded-md border border-[#C7D2FE] shadow-2xs">
                              {topTags.join(', ')}
                            </span>
                          )}
                        </div>

                        <div
                          className={`w-14 h-14 rounded-xl flex flex-col items-center justify-center font-mono text-base font-bold transition-all duration-200 border-2 relative ${
                            isSwapOp
                              ? 'bg-[#F3E8FF] text-[#6B21A8] border-[#A855F7] shadow-lg scale-110 ring-2 ring-[#C084FC]/50 z-10'
                              : isCompareOp
                              ? 'bg-[#FEF3C7] text-[#92400E] border-[#F59E0B] shadow-md scale-105 z-10'
                              : inWindow
                              ? 'bg-[#FFD166] text-[#4A3500] border-[#FFB703] shadow-md scale-105'
                              : isSorted
                              ? 'bg-[#ECFDF5] text-[#065F46] border-[#10B981] shadow-2xs'
                              : isAccessed
                              ? 'bg-[#EEF2FF] text-[#3B5BDB] border-[#3B5BDB] shadow-sm'
                              : 'bg-[#F8F9FA] text-[#1F2937] border-black/[0.08]'
                          }`}
                        >
                          <span>{String(val)}</span>
                          {isSorted && (
                            <span className="text-[9px] font-sans text-emerald-600 font-semibold absolute top-0.5 right-1">
                              ✓
                            </span>
                          )}
                        </div>

                        <span className="text-[11px] font-mono text-[#8A8A90] mt-1">
                          {idx}
                        </span>

                        <div className="h-6 flex items-start justify-center text-[11px] font-bold font-mono text-[#B33CF0] pt-0.5">
                          {bottomTags.length > 0 && (
                            <span className="bg-[#FAF5FF] text-[#B33CF0] px-1.5 py-0.2 rounded-md border border-[#E9D5FF] shadow-2xs">
                              {bottomTags.join(', ')}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* 3. HASHMAP & FREQUENCY TABLE STAGE */}
          {currentStep.hash_map_view && currentStep.hash_map_view.entries && currentStep.hash_map_view.entries.length > 0 && (
            <div className="bg-white rounded-2xl border border-black/[0.06] p-4 shadow-sm space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold text-[#44444C]">
                <div className="flex items-center gap-2 uppercase tracking-wider">
                  <Database className="w-3.5 h-3.5 text-[#6C5CFF]" />
                  <span>HashMap / Frequency Map: <code className="font-mono text-[#111113]">{currentStep.hash_map_view.entries.length} keys</code></span>
                </div>
                {currentStep.operation_type === 'map_update' && (
                  <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-md border border-emerald-200">
                    Updated Key
                  </span>
                )}
              </div>

              <div className="flex flex-wrap gap-2.5">
                {currentStep.hash_map_view.entries.map((entry, idx) => (
                  <div
                    key={idx}
                    className={`flex items-center gap-2 px-3 py-2 rounded-xl border font-mono text-xs transition-all ${
                      entry.was_updated
                        ? 'bg-[#FAF5FF] border-[#C084FC] shadow-sm ring-1 ring-[#C084FC]/40 scale-105'
                        : 'bg-[#F8F9FA] border-black/[0.08]'
                    }`}
                  >
                    <span className="text-[#6B6B73] font-semibold">{entry.key}:</span>
                    <span className="text-[#111113] font-bold">{String(entry.value)}</span>
                    {entry.was_updated && (
                      <span className="w-2 h-2 rounded-full bg-[#9333EA] animate-ping" />
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 4. STACK OR QUEUE STAGE */}
          {((currentStep.stack_view && currentStep.stack_view.length > 0) || (currentStep.queue_view && currentStep.queue_view.length > 0)) && (
            <div className="bg-white rounded-2xl border border-black/[0.06] p-4 shadow-sm space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold text-[#44444C]">
                <div className="flex items-center gap-2 uppercase tracking-wider">
                  <Layers className="w-3.5 h-3.5 text-[#6C5CFF]" />
                  <span>
                    {currentStep.stack_view ? 'Stack Stage (LIFO)' : 'Queue Stage (FIFO)'}
                  </span>
                </div>
                <span className="text-[11px] font-mono text-[#6C5CFF]">
                  size: {currentStep.stack_view ? currentStep.stack_view.length : currentStep.queue_view?.length}
                </span>
              </div>

              <div className="flex items-center gap-2 overflow-x-auto py-2">
                {(currentStep.stack_view || currentStep.queue_view || []).map((item, idx, arr) => {
                  const isTop = idx === arr.length - 1;
                  const isFront = idx === 0;
                  const formatted = formatQueueStackItem(item);
                  return (
                    <div
                      key={idx}
                      className={`h-11 px-4 rounded-xl flex items-center justify-center font-mono text-sm font-bold border-2 transition-all shrink-0 ${
                        isTop && currentStep.stack_view
                          ? 'bg-[#EEF2FF] text-[#3B5BDB] border-[#3B5BDB] shadow-md ring-2 ring-[#3B5BDB]/30'
                          : isFront && currentStep.queue_view
                          ? 'bg-[#ECFDF5] text-[#065F46] border-[#10B981] shadow-md'
                          : 'bg-[#F8F9FA] text-[#1F2937] border-black/[0.08]'
                      }`}
                    >
                      <span>{formatted}</span>
                      {isTop && currentStep.stack_view && (
                        <span className="ml-1.5 text-[9px] uppercase tracking-wider text-[#3B5BDB]">top</span>
                      )}
                      {isFront && currentStep.queue_view && (
                        <span className="ml-1.5 text-[9px] uppercase tracking-wider text-emerald-700">front</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 5. LINKED LIST STAGE */}
          {currentStep.linked_list_view && currentStep.linked_list_view.length > 0 && (
            <div className="bg-white rounded-2xl border border-black/[0.06] p-4 shadow-sm space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold text-[#44444C]">
                <div className="flex items-center gap-2 uppercase tracking-wider">
                  <GitBranch className="w-3.5 h-3.5 text-[#6C5CFF]" />
                  <span>Linked List Chain ({currentStep.linked_list_view.length} nodes)</span>
                </div>
              </div>

              <div className="flex items-center gap-2 overflow-x-auto py-2">
                {currentStep.linked_list_view.map((node, idx) => (
                  <React.Fragment key={node.id || idx}>
                    <div className="flex flex-col items-center shrink-0">
                      <div className="w-12 h-12 rounded-xl flex items-center justify-center bg-[#EEF2FF] text-[#3B5BDB] border-2 border-[#3B5BDB] font-mono text-sm font-bold shadow-xs">
                        {String(node.val)}
                      </div>
                      <span className="text-[9px] font-mono text-[#8A8A90] mt-1">
                        {idx === 0 ? 'head' : `node ${idx}`}
                      </span>
                    </div>
                    {node.next_id && (
                      <ArrowRight className="w-4 h-4 text-[#8A8A90] shrink-0" />
                    )}
                  </React.Fragment>
                ))}
              </div>
            </div>
          )}

          {/* 6. BINARY TREE VISUALIZER STAGE */}
          {currentStep.tree_view && currentStep.tree_view.length > 0 && (
            <div className="bg-white rounded-2xl border border-black/[0.06] p-4 shadow-sm space-y-4">
              <div className="flex items-center justify-between text-xs font-semibold text-[#44444C]">
                <div className="flex items-center gap-2 uppercase tracking-wider">
                  <Network className="w-3.5 h-3.5 text-[#6C5CFF]" />
                  <span>Binary Tree Hierarchy ({currentStep.tree_view.length} nodes)</span>
                </div>
                {primitiveVars.root !== undefined && (
                  <span className="text-[11px] font-mono text-[#6C5CFF] bg-[#6C5CFF]/10 px-2 py-0.5 rounded-md">
                    Target: {String(primitiveVars.val ?? primitiveVars.curr ?? primitiveVars.node ?? '')}
                  </span>
                )}
              </div>

              {/* Hierarchical tree layout arranged level by level */}
              <div className="overflow-x-auto py-2">
                <div className="flex flex-col items-center gap-6 min-w-min px-2 py-2">
                  {treeLevels.map(([depth, levelNodes]) => (
                    <div key={depth} className="flex flex-col items-center gap-2 w-full">
                      <div className="text-[10px] uppercase font-mono font-bold text-[#8A8A90] tracking-wider px-2 py-0.5 rounded bg-black/[0.03]">
                        {depth === 0 ? 'Root Level (Depth 0)' : `Depth ${depth}`}
                      </div>
                      <div className="flex flex-wrap items-center justify-center gap-6 sm:gap-8">
                        {levelNodes.map((node) => {
                          const active = isTreeNodeActive(node);
                          return (
                            <div
                              key={node.id}
                              className={`relative flex flex-col items-center p-3 rounded-2xl border-2 transition-all ${
                                active
                                  ? 'bg-[#F3E8FF] border-[#9333EA] shadow-lg scale-105 ring-4 ring-[#9333EA]/20'
                                  : 'bg-[#F8F9FA] border-black/[0.08] shadow-2xs hover:border-[#6C5CFF]/50'
                              }`}
                            >
                              {active && (
                                <span className="absolute -top-3.5 px-2 py-0.5 rounded-full bg-gradient-to-r from-[#B33CF0] to-[#6C5CFF] text-white text-[9px] font-bold uppercase tracking-wider shadow-sm animate-pulse">
                                  Visiting
                                </span>
                              )}
                              <div
                                className={`w-12 h-12 rounded-full flex items-center justify-center font-mono font-bold text-base transition-colors ${
                                  active
                                    ? 'bg-white border-2 border-[#9333EA] text-[#6B21A8]'
                                    : 'bg-white border-2 border-[#6C5CFF] text-[#6C5CFF]'
                                }`}
                              >
                                {String(node.val)}
                              </div>
                              <div className="flex items-center gap-2 mt-2 font-mono text-[10px] text-[#6B6B73]">
                                <span className={node.left_id ? 'text-indigo-600 font-semibold' : 'text-neutral-400'}>
                                  L: {node.left_id ? '✓' : '—'}
                                </span>
                                <span>•</span>
                                <span className={node.right_id ? 'text-indigo-600 font-semibold' : 'text-neutral-400'}>
                                  R: {node.right_id ? '✓' : '—'}
                                </span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 7. GRAPH EXPLORATION STAGE */}
          {currentStep.graph_view && currentStep.graph_view.nodes && currentStep.graph_view.nodes.length > 0 && (
            <div className="bg-white rounded-2xl border border-black/[0.06] p-4 shadow-sm space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold text-[#44444C]">
                <div className="flex items-center gap-2 uppercase tracking-wider">
                  <GitBranch className="w-3.5 h-3.5 text-[#6C5CFF]" />
                  <span>Graph Exploration Stage ({currentStep.graph_view.nodes.length} nodes)</span>
                </div>
                {currentStep.graph_view.current_node && (
                  <span className="text-[11px] font-mono text-purple-700 bg-purple-100 px-2 py-0.5 rounded-md border border-purple-200">
                    Visiting: node {currentStep.graph_view.current_node}
                  </span>
                )}
              </div>

              <div className="space-y-2">
                <div className="flex items-center gap-2 overflow-x-auto py-1">
                  {currentStep.graph_view.nodes.map((n) => {
                    const isVisited = currentStep.graph_view?.visited?.includes(String(n.id));
                    const isCurrent = String(currentStep.graph_view?.current_node) === String(n.id);
                    return (
                      <div
                        key={n.id}
                        className={`h-11 px-3.5 rounded-xl flex items-center justify-center font-mono text-xs font-bold border-2 transition-all shrink-0 ${
                          isCurrent
                            ? 'bg-[#F3E8FF] text-[#6B21A8] border-[#A855F7] shadow-md scale-105 ring-2 ring-[#A855F7]/30'
                            : isVisited
                            ? 'bg-[#ECFDF5] text-[#065F46] border-[#10B981] shadow-2xs'
                            : 'bg-[#F8F9FA] text-[#6B6B73] border-black/[0.08]'
                        }`}
                      >
                        <span>{n.label || n.id}</span>
                        {isVisited && !isCurrent && (
                          <span className="ml-1 text-[9px] text-emerald-600">✓</span>
                        )}
                      </div>
                    );
                  })}
                </div>

                {currentStep.graph_view.visited && currentStep.graph_view.visited.length > 0 && (
                  <div className="text-[11px] font-mono text-[#44444C] flex items-center gap-1.5 pt-1">
                    <span className="text-[#8A8A90]">Traversal order:</span>
                    <span className="font-semibold text-emerald-700">
                      {currentStep.graph_view.visited.join(' → ')}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 8. RECURSION CALL STACK */}
          {currentStep.call_stack && currentStep.call_stack.length > 0 && (
            <div className="bg-white rounded-2xl border border-black/[0.06] p-4 shadow-sm space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold text-[#44444C]">
                <div className="flex items-center gap-2 uppercase tracking-wider">
                  <Layers className="w-3.5 h-3.5 text-[#6C5CFF]" />
                  <span>Recursion Call Stack (Depth: {currentStep.call_stack.length})</span>
                </div>
                {currentStep.operation_type === 'call' && (
                  <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-700 bg-indigo-100 px-2 py-0.5 rounded-md border border-indigo-200 animate-pulse">
                    Push Frame
                  </span>
                )}
                {currentStep.operation_type === 'return' && (
                  <span className="text-[10px] font-bold uppercase tracking-wider text-amber-700 bg-amber-100 px-2 py-0.5 rounded-md border border-amber-200 animate-pulse">
                    Pop / Return
                  </span>
                )}
              </div>

              <div className="space-y-2">
                {currentStep.call_stack.map((frame, idx) => {
                  const isTop = idx === currentStep.call_stack!.length - 1;
                  const isReturning = frame.status === 'returning' || (isTop && currentStep.operation_type === 'return');
                  return (
                    <div
                      key={frame.frame_id || idx}
                      className={`flex items-center justify-between px-3.5 py-2.5 rounded-xl border text-xs font-mono transition-all ${
                        isReturning
                          ? 'bg-[#FEF3C7] border-[#F59E0B] text-[#92400E] shadow-sm ring-1 ring-[#F59E0B]/30'
                          : isTop
                          ? 'bg-[#EEF2FF] border-[#3B5BDB] text-[#3B5BDB] font-bold shadow-xs ring-2 ring-[#3B5BDB]/20'
                          : 'bg-[#F8F9FA] border-black/[0.06] text-[#6B6B73]'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-semibold">
                          {frame.func_name}({Object.entries(frame.args || {}).map(([k, v]) => `${k}=${v}`).join(', ')})
                        </span>
                        {isReturning && (
                          <span className="text-[10px] font-bold uppercase tracking-wider text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded border border-amber-300">
                            returning {frame.return_value !== undefined && frame.return_value !== null ? String(frame.return_value) : ''}
                          </span>
                        )}
                        {!isReturning && isTop && (
                          <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-700 bg-indigo-100 px-1.5 py-0.5 rounded">
                            active
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 text-[10px] opacity-75">
                        {frame.line_number && <span>line {frame.line_number}</span>}
                        <span>depth {frame.depth}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 7. VARIABLE STAT CARDS */}
          {Object.keys(primitiveVars).length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[#44444C] uppercase tracking-wider">
                <Sparkles className="w-3.5 h-3.5 text-[#6C5CFF]" />
                <span>Variable Inspector</span>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                {Object.entries(primitiveVars).map(([name, val]) => {
                  const wasChanged = changedVars.includes(name);
                  return (
                    <div
                      key={name}
                      className={`p-3 rounded-xl border transition-all duration-200 ${
                        wasChanged
                          ? 'bg-gradient-to-br from-[#FAF5FF] to-white border-[#C084FC] shadow-sm ring-1 ring-[#C084FC]/30'
                          : 'bg-white border-black/[0.06] shadow-2xs'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-medium text-[#6B6B73]">{name}</span>
                        {wasChanged && (
                          <span className="text-[9px] uppercase tracking-wider font-bold text-[#9333EA] bg-[#F3E8FF] px-1.5 py-0.2 rounded-md">
                            updated
                          </span>
                        )}
                      </div>
                      <div className="text-xl font-bold font-mono text-[#111113] mt-1 truncate">
                        {typeof val === 'string' ? `"${val}"` : String(val)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 8. CONTEXTUAL EXPLANATION CALLOUT */}
          {currentStep.explanation && (
            <div className="flex items-start gap-3 p-4 bg-white/90 rounded-2xl border border-black/[0.06] border-l-4 border-l-[#6C5CFF] shadow-2xs">
              <div className="w-8 h-8 rounded-xl bg-[#6C5CFF]/10 text-[#6C5CFF] flex items-center justify-center shrink-0 mt-0.5">
                <Sparkles className="w-4 h-4 stroke-[2]" />
              </div>
              <div className="space-y-1">
                <div className="text-xs font-semibold text-[#111113] flex items-center gap-2">
                  <span>Step {currentStep.step} Explanation</span>
                  <span className="text-[10px] text-[#8A8A90] font-mono">
                    (Line {currentStep.line_number})
                  </span>
                </div>
                <p className="text-xs text-[#44444C] leading-relaxed">
                  {currentStep.explanation}
                </p>
              </div>
            </div>
          )}

          {/* 9. DRY-RUN HISTORY TABLE */}
          <div className="bg-white rounded-2xl border border-black/[0.06] overflow-hidden flex flex-col shadow-xs">
            <div className="flex items-center justify-between px-4 py-2.5 bg-[#F8F9FA] border-b border-black/[0.05]">
              <div className="flex items-center gap-2">
                <TableProperties className="w-3.5 h-3.5 text-[#6C5CFF]" />
                <span className="text-xs font-semibold text-[#44444C]">Dry Run History Log</span>
              </div>
              <span className="text-[10px] text-[#8A8A90]">click row to jump</span>
            </div>

            <div ref={tableRef} className="flex-1 max-h-[300px] overflow-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead className="sticky top-0 bg-[#F8F9FA] border-b border-black/[0.05] text-[#6B6B73] font-semibold text-[11px]">
                  <tr>
                    <th className="py-2 px-3">#</th>
                    <th className="py-2 px-3">Line</th>
                    {historyColumns.map((col) => (
                      <th key={col} className="py-2 px-3 font-mono">{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/[0.03] font-mono text-[11.5px]">
                  {allSteps.map((step, idx) => {
                    const isSelected = idx === currentStepIndex;
                    return (
                      <tr
                        key={idx}
                        ref={isSelected ? activeRowRef : undefined}
                        onClick={() => onJumpToStep(idx)}
                        className={`cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-[#6C5CFF]/15 text-[#111113] font-bold border-l-3 border-[#6C5CFF]'
                            : 'hover:bg-black/[0.02] text-[#44444C]'
                        }`}
                      >
                        <td className="py-1.5 px-3">{step.step}</td>
                        <td className="py-1.5 px-3 text-[#6C5CFF]">{step.line_number}</td>
                        {historyColumns.map((col) => {
                          const val = step.local_vars?.[col];
                          return (
                            <td key={col} className="py-1.5 px-3 truncate max-w-[90px]">
                              {val !== undefined ? String(val) : '—'}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── Program Console ── */}
      <div className="bg-[#111113] rounded-2xl border border-black/10 overflow-hidden shadow-sm">
        <div className="flex items-center justify-between px-4 py-2 bg-white/[0.03] border-b border-white/[0.06]">
          <div className="flex items-center gap-2 text-white/70 text-xs">
            <Terminal className="w-3.5 h-3.5 text-[#3CC8FF]" />
            <span className="font-mono font-medium">Program Console</span>
          </div>
          <span className="text-[10px] text-white/40 font-mono">stdout / stderr</span>
        </div>

        <div className="p-4 font-mono text-xs text-white/90 max-h-48 overflow-y-auto space-y-2 whitespace-pre-wrap">
          {stdout && <div className="text-emerald-400">{stdout}</div>}
          {stderr && <div className="text-rose-400">{stderr}</div>}
          {!stdout && !stderr && (
            <div className="text-white/30 italic">No output produced.</div>
          )}
        </div>
      </div>
    </div>
  );
};
