/**
 * PlaygroundPage — Pebble Playground 2.0
 *
 * Professional two-panel interactive code learning & dry-run visualizer:
 *  - TOP SECTION: Shared Custom Input (stdin) centered above both panels
 *  - LEFT PANEL: User Code Editor with line numbers and active trace line highlighting
 *  - RIGHT PANEL: Live Visual Playground (Array stage, pointers, comparisons, swaps,
 *    variable inspector, contextual explanation, dry-run history table, program console)
 *  - Full keyboard shortcuts (Left/Right to step, Space to play/pause)
 *  - Multi-language support: Python, Java, and C++
 */

import React, { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { HexBackground } from '../HexBackground.tsx';
import {
  Code2,
  Lightbulb,
  Copy,
  Check,
  ChevronLeft,
  RotateCcw,
  Play,
  Terminal,
  Layers,
  Sparkles,
  BookOpen,
} from 'lucide-react';
import {
  PlaygroundMode,
  PlaygroundLanguage,
  PlaygroundResponse,
  ExecuteResponse,
  PLAYGROUND_PRESETS,
  PlaygroundPreset,
  submitPlayground,
  executeCode,
  loadPlaygroundDraft,
  savePlaygroundDraft,
} from '../../lib/playground.ts';
import { useExecutionTrace } from '../../hooks/useExecutionTrace.ts';
import { StepperControls } from './StepperControls.tsx';
import { VisualizerCanvas } from './VisualizerCanvas.tsx';

// ─── Types ───────────────────────────────────────────────────────────────────

interface PlaygroundPageProps {
  onGoBack: () => void;
}

type UIState = 'idle' | 'loading' | 'result' | 'error';

// ─── Helpers ─────────────────────────────────────────────────────────────────

const LANG_LABELS: Record<PlaygroundLanguage, string> = {
  python: 'Python',
  java: 'Java',
  cpp: 'C++',
};

// ─── Main Component ───────────────────────────────────────────────────────────

export const PlaygroundPage: React.FC<PlaygroundPageProps> = ({ onGoBack }) => {
  // Always start with a clean slate — empty editor and input.
  // Draft is only used for restoring mode and language preference, never code content.
  const draft = loadPlaygroundDraft();

  const [mode, setMode] = useState<PlaygroundMode>(draft.mode);
  const [language, setLanguage] = useState<PlaygroundLanguage>(draft.language);
  const [code, setCode] = useState('');
  const [problem, setProblem] = useState('');
  const [customInput, setCustomInput] = useState('');

  const [uiState, setUiState] = useState<UIState>('idle');
  const [result, setResult] = useState<PlaygroundResponse | null>(null);
  const [executionResult, setExecutionResult] = useState<ExecuteResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [copied, setCopied] = useState(false);

  // Stepper trace hook
  const {
    steps,
    currentStepIndex,
    currentStep,
    totalSteps,
    isPlaying,
    playSpeedMs,
    setPlaySpeedMs,
    goNext,
    goPrev,
    play,
    pause,
    reset: resetStepper,
    jumpToStep,
    setSteps,
  } = useExecutionTrace();

  const abortRef = useRef<AbortController | null>(null);
  const codeRef = useRef<HTMLTextAreaElement>(null);

  // Persist mode & language preference
  useEffect(() => {
    savePlaygroundDraft({ mode, language, code, problem, customInput });
  }, [mode, language, code, problem, customInput]);

  const validate = (): string | null => {
    if (mode === 'explain') {
      if (!code.trim()) return 'Please enter or paste your code before running.';
    } else {
      if (!problem.trim()) return 'Please describe the problem you want to solve.';
    }
    return null;
  };

  // Preset selector — confirm before replacing user code
  const handleSelectPreset = (preset: PlaygroundPreset) => {
    if (
      code.trim().length > 0 &&
      !window.confirm(`Load the "${preset.title}" example? This will replace your current code.`)
    ) {
      return;
    }
    setMode('explain');
    const targetCode = (language === 'java' && preset.javaCode) ? preset.javaCode : preset.code;
    const targetLang = (language === 'java' && preset.javaCode) ? 'java' : preset.language;
    setLanguage(targetLang);
    setCode(targetCode);
    setCustomInput(preset.custom_input);
    setResult(null);
    setExecutionResult(null);
    setSteps([]);
    setErrorMsg('');
  };

  // Language switcher
  const handleLanguageChange = (newLang: PlaygroundLanguage) => {
    setLanguage(newLang);
    // If user has a preset loaded, switch to the matching code for the new language
    const matchingPreset = PLAYGROUND_PRESETS.find(p => p.code === code || p.javaCode === code);
    if (matchingPreset) {
      if (newLang === 'java' && matchingPreset.javaCode) {
        setCode(matchingPreset.javaCode);
      } else if (newLang === 'python') {
        setCode(matchingPreset.code);
      }
    }
    setExecutionResult(null);
    setSteps([]);
  };

  // Helper to execute code in sandbox and populate visualizer
  const executeCodeInSandbox = useCallback(
    async (codeToRun: string, signal?: AbortSignal) => {
      const execRes = await executeCode(
        {
          language,
          code: codeToRun,
          custom_input: customInput.trim() || undefined,
        },
        signal
      );
      setExecutionResult(execRes);
      if (execRes.trace_steps && execRes.trace_steps.length > 0) {
        setSteps(execRes.trace_steps);
      } else {
        setSteps([]);
      }
      return execRes;
    },
    [language, customInput, setSteps]
  );

  const handleRun = useCallback(async () => {
    const validationError = validate();
    if (validationError) {
      setErrorMsg(validationError);
      setUiState('error');
      return;
    }

    if (uiState === 'loading') return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setUiState('loading');
    setResult(null);
    setExecutionResult(null);
    setSteps([]);
    setErrorMsg('');

    try {
      if (mode === 'explain') {
        // Run sandbox execution AND algorithm explanation in parallel
        const [explRes, execRes] = await Promise.all([
          submitPlayground(
            {
              mode: 'explain',
              language,
              code,
              custom_input: customInput.trim() || undefined,
            },
            controller.signal
          ),
          executeCode(
            {
              language,
              code,
              custom_input: customInput.trim() || undefined,
            },
            controller.signal
          ),
        ]);

        setResult(explRes);
        setExecutionResult(execRes);
        if (execRes.trace_steps && execRes.trace_steps.length > 0) {
          setSteps(execRes.trace_steps);
        }
        setUiState('result');
      } else {
        // Solve mode: get solution first
        const solveRes = await submitPlayground(
          {
            mode: 'solve',
            language,
            problem,
            custom_input: customInput.trim() || undefined,
          },
          controller.signal
        );

        setResult(solveRes);

        // If a solution code was generated, execute it in the sandbox
        if (solveRes.status === 'ok' && solveRes.solution_code && !solveRes.solution_code.startsWith('# LLM not configured')) {
          try {
            const execRes = await executeCode(
              {
                language,
                code: solveRes.solution_code,
                custom_input: customInput.trim() || undefined,
              },
              controller.signal
            );
            setExecutionResult(execRes);
            if (execRes.trace_steps && execRes.trace_steps.length > 0) {
              setSteps(execRes.trace_steps);
            }
          } catch {
            // Non-fatal if execution fails on mock code
          }
        }

        setUiState('result');
      }
    } catch (err: any) {
      if (err?.name === 'AbortError') return;
      const msg = err?.message || 'Something went wrong. Please try again.';
      setErrorMsg(msg);
      setUiState('error');
    }
  }, [mode, language, code, problem, customInput, uiState, setSteps]);

  const handleReset = () => {
    abortRef.current?.abort();
    resetStepper();
    setSteps([]);
    setUiState('idle');
    setResult(null);
    setExecutionResult(null);
    setErrorMsg('');
  };

  const handleCopyCode = () => {
    const textToCopy = mode === 'explain' ? code : (result?.solution_code || code);
    if (!textToCopy) return;
    navigator.clipboard.writeText(textToCopy).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const isLoading = uiState === 'loading';
  const hasResult = uiState === 'result' && (result !== null || executionResult !== null);

  // Line calculations for Left Panel code editor
  const displayCode = mode === 'explain' ? code : (result?.solution_code || '');
  const editorLines = useMemo(() => {
    return displayCode ? displayCode.split('\n') : [''];
  }, [displayCode]);

  return (
    <div className="fixed inset-0 z-30 bg-[#F7F7F8] p-2 flex overflow-hidden select-none">
      {/* Inner container */}
      <div
        className="relative flex-1 bg-[#ECECEE] rounded-[24px] sm:rounded-[28px] flex flex-col overflow-hidden border border-black/[0.04]"
        style={{
          boxShadow: 'inset 0 1px 2px rgba(255, 255, 255, 0.8), 0 12px 36px rgba(0, 0, 0, 0.03)',
        }}
      >
        {/* Hex background */}
        <div className="absolute inset-0 z-0 pointer-events-none rounded-[24px] sm:rounded-[28px] overflow-hidden opacity-40">
          <HexBackground isStatic />
        </div>

        {/* ── TOP HEADER BAR ── */}
        <header className="relative z-10 w-full h-14 border-b border-black/[0.05] px-4 sm:px-6 flex items-center justify-between bg-white/40 backdrop-blur-md shrink-0">
          <div className="flex items-center gap-3">
            {/* Back button */}
            <button
              type="button"
              onClick={onGoBack}
              data-cursor="button"
              title="Back to chat"
              className="w-8 h-8 rounded-xl flex items-center justify-center text-[#6B6B73] hover:text-[#111113] hover:bg-white/70 transition-all cursor-pointer"
            >
              <ChevronLeft className="w-5 h-5 stroke-[2]" />
            </button>

            {/* Pebble logo glyph */}
            <div
              className="w-7 h-6 rounded-[48%_52%_68%_32%_/_42%_44%_56%_58%] p-[2px] shadow-xs"
              style={{ background: 'linear-gradient(135deg, #B33CF0 0%, #6C5CFF 50%, #3CC8FF 100%)' }}
            >
              <div className="w-full h-full bg-[#121217] rounded-[46%_54%_66%_34%_/_40%_42%_58%_60%] flex items-center justify-center gap-0.5 px-0.5">
                <span className="w-0.5 h-1.5 bg-gradient-to-b from-white to-[#C7D2FE] rounded-full" />
                <span className="w-0.5 h-1.5 bg-gradient-to-b from-white to-[#A5F3FC] rounded-full" />
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="font-semibold text-xs uppercase tracking-wider text-[#8A8A90]">pebble</span>
              <span className="text-xs text-[#C0C0C6]">/</span>
              <span className="font-semibold text-sm text-[#111113]">Playground 2.0</span>
            </div>
          </div>

          {/* Mode Switcher Tabs */}
          <div className="flex items-center gap-1 p-0.5 bg-black/[0.04] rounded-xl">
            <button
              type="button"
              onClick={() => setMode('explain')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                mode === 'explain'
                  ? 'bg-white text-[#111113] shadow-xs'
                  : 'text-[#6B6B73] hover:text-[#111113]'
              }`}
            >
              <Code2 className="w-3.5 h-3.5 text-[#6C5CFF]" />
              <span>Explain & Dry Run</span>
            </button>
            <button
              type="button"
              onClick={() => setMode('solve')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                mode === 'solve'
                  ? 'bg-white text-[#111113] shadow-xs'
                  : 'text-[#6B6B73] hover:text-[#111113]'
              }`}
            >
              <Lightbulb className="w-3.5 h-3.5 text-amber-500" />
              <span>Solve a Problem</span>
            </button>
          </div>

          {/* Status pill */}
          <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/70 border border-black/[0.06] text-[11px] font-medium text-[#44444C]">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isLoading ? 'bg-[#3CC8FF] animate-pulse' : 'bg-emerald-500'
              }`}
            />
            <span>{isLoading ? 'running in sandbox…' : 'ready'}</span>
          </div>
        </header>

        {/* ── SCROLLABLE BODY ── */}
        <div className="relative z-10 flex-1 overflow-y-auto px-4 sm:px-6 py-4 space-y-4">
          <div className="max-w-[1480px] mx-auto space-y-4">

            {/* ═══════════════════════════════════════════════════════════════
                TOP SECTION: Shared Custom Input (stdin) & Presets
                ═══════════════════════════════════════════════════════════════ */}
            <div
              className="bg-white/80 rounded-2xl border border-black/[0.06] p-4 shadow-sm space-y-2.5"
              style={{ boxShadow: '0 2px 10px rgba(0,0,0,0.03)' }}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-xs font-semibold text-[#44444C] uppercase tracking-wider">
                  <Terminal className="w-3.5 h-3.5 text-[#6C5CFF]" />
                  <span>Custom Test Input (stdin)</span>
                  <span className="text-[11px] font-normal text-[#8A8A90] lowercase tracking-normal">
                    — shared between code execution & visualizer
                  </span>
                </div>

                {/* Preset quick pills */}
                <div className="flex items-center gap-1.5 overflow-x-auto py-0.5">
                  <span className="text-[11px] font-semibold text-[#6B6B73] flex items-center gap-1">
                    <BookOpen className="w-3 h-3 text-[#6C5CFF]" />
                    Presets:
                  </span>
                  {PLAYGROUND_PRESETS.map((preset) => (
                    <button
                      key={preset.id}
                      type="button"
                      onClick={() => handleSelectPreset(preset)}
                      data-cursor="button"
                      title={preset.description}
                      className="px-2.5 py-1 rounded-xl bg-white border border-black/[0.08] text-[11px] font-medium text-[#333339] hover:border-[#6C5CFF]/40 hover:text-[#6C5CFF] shadow-2xs transition-all cursor-pointer shrink-0"
                    >
                      {preset.title}
                    </button>
                  ))}
                </div>
              </div>

              <textarea
                value={customInput}
                onChange={(e) => setCustomInput(e.target.value)}
                placeholder="Provide standard input to pass to your program (e.g., 5 1 4 2 8 or [2, 7, 11, 15] or target sum)..."
                rows={2}
                className="w-full resize-none bg-black/[0.02] border border-black/[0.06] rounded-xl font-mono text-[13px] text-[#1F1F24] placeholder:text-[#A0A0A8] leading-relaxed outline-none px-3.5 py-2.5 focus:border-[#6C5CFF]/40 focus:bg-white transition-colors"
              />
            </div>

            {/* Error banner if validation or runtime error occurred */}
            {uiState === 'error' && (
              <div className="bg-red-50 border border-red-200/80 rounded-2xl px-4 py-3 text-sm text-red-700 shadow-2xs">
                {errorMsg}
              </div>
            )}

            {/* ═══════════════════════════════════════════════════════════════
                MAIN SECTION: Responsive Side-by-Side Panels
                ═══════════════════════════════════════════════════════════════ */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">

              {/* ─────────────────────────────────────────────────────────────
                  LEFT PANEL: User Code Editor (Single Source of Truth)
                  ───────────────────────────────────────────────────────────── */}
              <div
                className="bg-white/80 rounded-2xl border border-black/[0.06] shadow-sm flex flex-col overflow-hidden"
                style={{ boxShadow: '0 2px 12px rgba(0,0,0,0.03)' }}
              >
                {/* Header bar */}
                <div className="flex items-center justify-between px-4 py-2.5 bg-white/70 border-b border-black/[0.05]">
                  <div className="flex items-center gap-2">
                    <Code2 className="w-4 h-4 text-[#6C5CFF]" />
                    <span className="text-xs font-semibold text-[#44444C] uppercase tracking-wider">
                      {mode === 'explain' ? 'Your Code' : 'Problem / Solution'}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    {/* Language selector */}
                    <div className="flex items-center gap-0.5 p-0.5 bg-black/[0.04] rounded-xl">
                      {(['python', 'java', 'cpp'] as PlaygroundLanguage[]).map((lang) => (
                        <button
                          key={lang}
                          type="button"
                          onClick={() => handleLanguageChange(lang)}
                          data-cursor="button"
                          className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all cursor-pointer ${
                            language === lang
                              ? 'bg-white text-[#111113] shadow-2xs'
                              : 'text-[#6B6B73] hover:text-[#111113]'
                          }`}
                        >
                          {LANG_LABELS[lang]}
                        </button>
                      ))}
                    </div>

                    {/* Copy code button */}
                    <button
                      type="button"
                      onClick={handleCopyCode}
                      title="Copy code"
                      className="p-1.5 rounded-lg text-[#6B6B73] hover:text-[#111113] hover:bg-black/[0.04] transition-colors cursor-pointer"
                    >
                      {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                </div>

                {/* Editor Body */}
                <div className="p-3">
                  {mode === 'explain' ? (
                    /* Explain mode: Editable Code with synchronized Line Numbers & Active Line Highlight */
                    <div className="relative rounded-xl overflow-hidden border border-black/[0.08] bg-[#141416] flex flex-col min-h-[440px]">
                      {/* Top editor mini-bar */}
                      <div className="flex items-center justify-between px-3.5 py-2 bg-[#1A1A1E] border-b border-white/[0.06]">
                        <div className="flex items-center gap-1.5">
                          <div className="w-2.5 h-2.5 rounded-full bg-[#FF5F57]" />
                          <div className="w-2.5 h-2.5 rounded-full bg-[#FEBC2E]" />
                          <div className="w-2.5 h-2.5 rounded-full bg-[#28C840]" />
                        </div>
                        <span className="text-[11px] font-mono text-[#8A8A90] uppercase tracking-wider">
                          {language}
                        </span>
                        {currentStep && currentStep.line_number > 0 && (
                          <span className="text-[11px] font-mono font-bold text-[#3CC8FF] bg-[#3CC8FF]/10 px-2 py-0.5 rounded-md border border-[#3CC8FF]/20">
                            Active: Line {currentStep.line_number}
                          </span>
                        )}
                      </div>

                      {/* Code Area with Line Numbers */}
                      <div className="flex flex-1 overflow-x-auto text-[13px] leading-6 font-mono py-2">
                        {/* Line numbers gutter */}
                        <div className="select-none px-2.5 text-right font-mono text-xs shrink-0 border-r border-white/[0.06]">
                          {editorLines.map((_, i) => {
                            const lineNo = i + 1;
                            const isCurrent = currentStep?.line_number === lineNo;
                            return (
                              <div
                                key={i}
                                className={`h-6 flex items-center justify-end gap-1 px-1 rounded transition-colors ${
                                  isCurrent
                                    ? 'text-[#3CC8FF] font-bold bg-[#3CC8FF]/25'
                                    : 'text-[#52525B]'
                                }`}
                              >
                                {isCurrent && <span className="text-[10px] text-[#3CC8FF]">▶</span>}
                                <span>{lineNo}</span>
                              </div>
                            );
                          })}
                        </div>

                        {/* Interactive Code Textarea */}
                        <div className="relative flex-1">
                          {/* Active line background marker */}
                          {currentStep && currentStep.line_number > 0 && (
                            <div
                              className="absolute left-0 right-0 pointer-events-none bg-[#6C5CFF]/15 border-l-2 border-[#3CC8FF] transition-all duration-150"
                              style={{
                                top: `${(currentStep.line_number - 1) * 24}px`,
                                height: '24px',
                              }}
                            />
                          )}
                          <textarea
                            ref={codeRef}
                            value={code}
                            onChange={(e) => {
                              setCode(e.target.value);
                              if (executionResult) {
                                setExecutionResult(null);
                                setSteps([]);
                              }
                            }}
                            placeholder={'Paste or write your code here...\n\nTip: Load a preset above or write any algorithm to dry-run.'}
                            spellCheck={false}
                            data-cursor="input"
                            className="w-full h-full min-h-[400px] resize-none bg-transparent font-mono text-[13px] text-[#E2E2E8] placeholder:text-[#6B6B73] leading-6 outline-none px-3 py-0 overflow-auto whitespace-pre"
                          />
                        </div>
                      </div>
                    </div>
                  ) : (
                    /* Solve mode: Problem description input or solution code display */
                    <div className="space-y-3">
                      <div className="rounded-xl border border-black/[0.08] bg-[#FDFDFD] p-3 space-y-1.5">
                        <span className="text-xs font-semibold text-[#44444C]">Problem Statement</span>
                        <textarea
                          value={problem}
                          onChange={(e) => setProblem(e.target.value)}
                          placeholder={'Describe the problem you want to solve...\n\nExample: Given an array of integers and a target sum, find two indices whose values add up to the target.'}
                          rows={4}
                          className="w-full resize-none bg-transparent font-mono text-[13px] text-[#1F1F24] placeholder:text-[#A0A0A8] leading-relaxed outline-none"
                        />
                      </div>

                      {result?.solution_code && (
                        <div className="rounded-xl overflow-hidden border border-black/[0.08] bg-[#141416] p-3 space-y-2">
                          <div className="flex items-center justify-between text-xs font-semibold text-[#E2E2E8]">
                            <span>Generated Solution Code</span>
                            {currentStep && currentStep.line_number > 0 && (
                              <span className="font-mono text-[#3CC8FF]">Line {currentStep.line_number}</span>
                            )}
                          </div>
                          <div className="flex overflow-x-auto text-[13px] leading-6 font-mono py-2 max-h-[340px]">
                            <div className="select-none px-2.5 text-right font-mono text-xs shrink-0 border-r border-white/[0.06]">
                              {editorLines.map((_, i) => (
                                <div
                                  key={i}
                                  className={`h-6 ${currentStep?.line_number === i + 1 ? 'text-[#3CC8FF] font-bold bg-[#3CC8FF]/20' : 'text-[#52525B]'}`}
                                >
                                  {i + 1}
                                </div>
                              ))}
                            </div>
                            <pre className="flex-1 px-3 text-[#E2E2E8] whitespace-pre overflow-visible">
                              {result.solution_code}
                            </pre>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Left Panel Action Bar: Run / Reset Buttons */}
                <div className="px-4 py-3 bg-white/60 border-t border-black/[0.05] flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleRun}
                      disabled={isLoading}
                      data-cursor="button"
                      className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-semibold text-white transition-all cursor-pointer shadow-sm active:scale-95 ${
                        isLoading
                          ? 'opacity-60 cursor-not-allowed'
                          : 'hover:scale-[1.02] hover:shadow-md'
                      }`}
                      style={{ background: 'linear-gradient(135deg, #B33CF0 0%, #6C5CFF 50%, #3CC8FF 100%)' }}
                    >
                      {isLoading ? (
                        <>
                          <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                          <span>Running in Sandbox…</span>
                        </>
                      ) : (
                        <>
                          <Play className="w-3.5 h-3.5 fill-current" />
                          <span>{mode === 'explain' ? 'Run & Trace' : 'Solve & Dry Run'}</span>
                        </>
                      )}
                    </button>

                    {(uiState === 'result' || uiState === 'error') && (
                      <button
                        type="button"
                        onClick={handleReset}
                        data-cursor="button"
                        className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium text-[#6B6B73] hover:text-[#111113] hover:bg-black/[0.04] transition-all cursor-pointer"
                      >
                        <RotateCcw className="w-3 h-3" />
                        <span>Reset</span>
                      </button>
                    )}
                  </div>

                  <span className="text-[11px] font-mono text-[#8A8A90]">
                    {language.toUpperCase()} Sandbox
                  </span>
                </div>

                {/* Approach & Explanation Cards (if available) */}
                {hasResult && result && (
                  <div className="p-4 border-t border-black/[0.05] bg-white/40 space-y-3">
                    {result.approach && (
                      <div className="bg-white rounded-xl border border-black/[0.06] p-3 space-y-1 shadow-2xs">
                        <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#44444C] uppercase tracking-wider">
                          <Sparkles className="w-3.5 h-3.5 text-[#6C5CFF]" />
                          <span>Approach Summary</span>
                        </div>
                        <p className="text-xs text-[#333339] leading-relaxed">{result.approach}</p>
                      </div>
                    )}
                    {result.explanation && (
                      <div className="bg-white rounded-xl border border-black/[0.06] p-3 space-y-1 shadow-2xs">
                        <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#44444C] uppercase tracking-wider">
                          <Layers className="w-3.5 h-3.5 text-[#6C5CFF]" />
                          <span>Algorithm Overview</span>
                        </div>
                        <p className="text-xs text-[#333339] leading-relaxed whitespace-pre-line">{result.explanation}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* ─────────────────────────────────────────────────────────────
                  RIGHT PANEL: Live Visual Playground Canvas
                  ───────────────────────────────────────────────────────────── */}
              <div
                className="bg-white/80 rounded-2xl border border-black/[0.06] shadow-sm flex flex-col overflow-hidden"
                style={{ boxShadow: '0 2px 12px rgba(0,0,0,0.03)' }}
              >
                {/* Header with Stepper Controls */}
                <div className="border-b border-black/[0.05] bg-white/70">
                  <StepperControls
                    currentStepIndex={currentStepIndex}
                    totalSteps={totalSteps}
                    isPlaying={isPlaying}
                    stepDescription={currentStep?.description}
                    playSpeedMs={playSpeedMs}
                    onSetPlaySpeedMs={setPlaySpeedMs}
                    onPrev={goPrev}
                    onNext={goNext}
                    onPlay={play}
                    onPause={pause}
                    onReset={resetStepper}
                    disabled={!executionResult || totalSteps === 0}
                  />
                </div>

                {/* Visualizer Canvas Content */}
                <div className="flex-1 overflow-y-auto">
                  <VisualizerCanvas
                    code={displayCode}
                    executionResult={executionResult}
                    currentStep={currentStep}
                    currentStepIndex={currentStepIndex}
                    totalSteps={totalSteps}
                    allSteps={steps}
                    language={LANG_LABELS[language]}
                    onJumpToStep={jumpToStep}
                  />
                </div>
              </div>

            </div>

            {/* Bottom spacer */}
            <div className="h-6" />
          </div>
        </div>
      </div>
    </div>
  );
};
