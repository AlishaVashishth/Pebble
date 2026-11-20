/**
 * VisualizerCanvas — Pebble Playground 2.0 Visual Execution & Dry-Run Canvas.
 *
 * Inspired by the Sliding Window playground design:
 *  - Animated Array Stage with top & bottom pointer tags, active window highlights, and index numbers
 *  - Prominent Stat Cards for variables with change indicators
 *  - Beginner-Friendly Contextual Explanation callout
 *  - Dry-Run History Table with interactive step-jumping and active-row auto-scrolling
 *  - Synchronized line-highlighted code viewer
 *  - Program console (stdout, stderr, exit code, execution time)
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
  const lines = useMemo(() => code.split('\n'), [code]);
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

  // Separate array variables vs primitive variables.
  // When the current step has empty locals (common at step 0), look ahead
  // to find the first step that has data so the canvas isn't blank.
  const { arrayVars, primitiveVars, primaryArrayName, primaryArray } = useMemo(() => {
    // Find the effective step — current step, or look-ahead if locals are empty
    let effectiveStep = currentStep;
    if (
      effectiveStep &&
      effectiveStep.local_vars &&
      Object.keys(effectiveStep.local_vars).length === 0 &&
      allSteps.length > 1
    ) {
      // Look ahead to the nearest step with meaningful state
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
      } else {
        primitives[key] = val;
      }
    }

    // Determine primary array
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

  // Collect key columns for the dry-run history table
  const historyColumns = useMemo(() => {
    const keys = new Set<string>();
    // Collect from first few steps
    for (const s of allSteps.slice(0, 25)) {
      if (s.local_vars) {
        for (const [k, v] of Object.entries(s.local_vars)) {
          if (!Array.isArray(v) && typeof v !== 'object') {
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
          // Top: left, low, i, start, slow, first
          if (['left', 'low', 'i', 'start', 'slow', 'first', 'l'].includes(lower)) {
            if (!top[idx]) top[idx] = [];
            top[idx].push(name);
          } else {
            // Bottom: right, high, j, end, fast, mid, r
            if (!bottom[idx]) bottom[idx] = [];
            bottom[idx].push(name);
          }
        }
      }
    }
    return { topPointers: top, bottomPointers: bottom };
  }, [currentStep]);

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

      {/* ── Active Visual Execution Section (Python & Java Trace Ready) ── */}
      {trace_available && currentStep && (
        <div className="space-y-5">
          {/* 1. ARRAY STAGE & POINTER CANVAS (Inspired by Sliding window playground.html & Bubble Sort Visualizer) */}
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

                    // Sorted detection (e.g. Bubble sort where indices >= n - i are sorted)
                    const nVal = Number(primitiveVars.n || primitiveVars.len || primitiveVars.size);
                    const iVal = Number(primitiveVars.i);
                    const isSortedTail = Number.isFinite(nVal) && Number.isFinite(iVal) && nVal > 0 && iVal >= 0 && idx >= nVal - iVal;
                    const isAllSorted = currentStepIndex === totalSteps - 1 && isOk;
                    const isSorted = isSortedTail || isAllSorted;

                    return (
                      <div key={idx} className="flex flex-col items-center shrink-0 w-14 select-none">
                        {/* Top Pointer Badge */}
                        <div className="h-6 flex items-end justify-center text-[11px] font-bold font-mono text-[#3B5BDB] pb-0.5">
                          {topTags.length > 0 && (
                            <span className="bg-[#EEF2FF] text-[#3B5BDB] px-1.5 py-0.2 rounded-md border border-[#C7D2FE] shadow-2xs">
                              {topTags.join(', ')}
                            </span>
                          )}
                        </div>

                        {/* Cell Box */}
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

                        {/* Index Number */}
                        <span className="text-[11px] font-mono text-[#8A8A90] mt-1">
                          {idx}
                        </span>

                        {/* Bottom Pointer Badge */}
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

          {/* 2. VARIABLE STAT CARDS (Inspired by .stats in Sliding window playground.html) */}
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

          {/* 3. CONTEXTUAL EXPLANATION CALLOUT (.msg in Sliding window playground.html) */}
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

          {/* 4. DRY-RUN HISTORY TABLE */}
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
                              {val !== undefined ? String(val) : '-'}
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

      {/* ── Standard Program Console ── */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-[#44444C] uppercase tracking-wider">
          <Terminal className="w-3.5 h-3.5 text-[#8A8A90]" />
          <span>Program Console</span>
        </div>

        <div className="rounded-2xl border border-black/[0.07] bg-[#141416] p-4 font-mono text-xs text-[#E2E2E8] space-y-2">
          {stdout && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[#8A8A90] mb-1 font-sans">
                Standard Output (stdout)
              </div>
              <pre className="whitespace-pre-wrap leading-relaxed text-[#A7F3D0]">
                {stdout}
              </pre>
            </div>
          )}

          {stderr && (
            <div className={stdout ? 'pt-2 border-t border-white/[0.06]' : ''}>
              <div className="text-[10px] uppercase tracking-wider text-rose-400 mb-1 font-sans">
                {isCompileError ? 'Compiler Diagnostics' : 'Standard Error (stderr)'}
              </div>
              <pre className="whitespace-pre-wrap leading-relaxed text-rose-300">
                {stderr}
              </pre>
            </div>
          )}

          {!stdout && !stderr && (
            <div className="text-[#6B6B73] italic">
              Program completed with no console output.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
