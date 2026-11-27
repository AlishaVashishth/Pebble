/**
 * StepperControls — Interactive playback & dry-run stepper controls for Pebble Playground 2.0.
 *
 * Inspired by professional algorithmic visualizers:
 *  - Play / Pause / Step Back / Step Forward / Restart
 *  - Progress bar across total execution steps
 *  - Playback speed switcher (0.5x, 1x, 1.5x, 2x)
 *  - Keyboard shortcut hints (← / → to step)
 */

import React, { useEffect } from 'react';
import {
  Play,
  Pause,
  ChevronLeft,
  ChevronRight,
  RotateCcw,
  FastForward,
  Gauge,
  Sliders,
} from 'lucide-react';

interface StepperControlsProps {
  currentStepIndex: number;
  totalSteps: number;
  isPlaying: boolean;
  stepDescription?: string;
  playSpeedMs: number;
  onSetPlaySpeedMs: (speedMs: number) => void;
  onPrev: () => void;
  onNext: () => void;
  onPlay: () => void;
  onPause: () => void;
  onReset: () => void;
  disabled?: boolean;
}

const SPEED_OPTIONS = [
  { label: '0.5x', ms: 1800 },
  { label: '1x', ms: 1100 },
  { label: '1.5x', ms: 700 },
  { label: '2x', ms: 400 },
];

export const StepperControls: React.FC<StepperControlsProps> = ({
  currentStepIndex,
  totalSteps,
  isPlaying,
  stepDescription,
  playSpeedMs,
  onSetPlaySpeedMs,
  onPrev,
  onNext,
  onPlay,
  onPause,
  onReset,
  disabled = false,
}) => {
  const hasSteps = totalSteps > 0 && !disabled;
  const canGoPrev = hasSteps && currentStepIndex > 0;
  const canGoNext = hasSteps && currentStepIndex < totalSteps - 1;
  const progressPercent = totalSteps > 0 ? ((currentStepIndex + 1) / totalSteps) * 100 : 0;

  // Global keyboard shortcuts (Left Arrow: Prev, Right Arrow: Next, Space: Play/Pause)
  useEffect(() => {
    if (!hasSteps) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept if user is typing in an input or textarea
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) {
        return;
      }

      if (e.key === 'ArrowRight') {
        e.preventDefault();
        if (canGoNext) onNext();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        if (canGoPrev) onPrev();
      } else if (e.key === ' ' || e.code === 'Space') {
        e.preventDefault();
        if (isPlaying) {
          onPause();
        } else {
          onPlay();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [hasSteps, canGoNext, canGoPrev, isPlaying, onNext, onPrev, onPlay, onPause]);

  return (
    <div className="flex flex-col bg-white/70 border-b border-black/[0.06] select-none">
      {/* Progress bar line */}
      <div className="w-full h-1 bg-black/[0.04] overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-[#B33CF0] via-[#6C5CFF] to-[#3CC8FF] transition-all duration-200"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
        {/* Step indicator badge & progress */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-white border border-black/[0.06] shadow-2xs">
            <span className="font-mono text-xs font-bold text-[#111113]">
              {hasSteps ? `Step ${currentStepIndex + 1}` : 'Step 0'}
            </span>
            <span className="text-[11px] font-mono text-[#8A8A90]">
              / {hasSteps ? totalSteps : 0}
            </span>
          </div>

          {hasSteps && (
            <span className="text-[11px] font-medium text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-lg border border-emerald-200/60 hidden sm:inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Live Stepper
            </span>
          )}
        </div>

        {/* Playback action controls */}
        <div className="flex items-center gap-1">
          {/* Reset / Restart */}
          <button
            type="button"
            onClick={onReset}
            disabled={!hasSteps || currentStepIndex === 0}
            data-cursor="button"
            title="Restart from step 1"
            className={`p-2 rounded-xl border transition-all cursor-pointer ${
              hasSteps && currentStepIndex > 0
                ? 'bg-white text-[#44444C] border-black/[0.08] hover:bg-[#F2F2F4] hover:text-[#111113] shadow-xs active:scale-95'
                : 'text-[#B0B0B8] border-transparent cursor-not-allowed opacity-40'
            }`}
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>

          {/* Previous Step */}
          <button
            type="button"
            onClick={onPrev}
            disabled={!canGoPrev}
            data-cursor="button"
            title="Previous step (Left Arrow)"
            className={`flex items-center gap-1 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer ${
              canGoPrev
                ? 'bg-white text-[#333339] border-black/[0.08] hover:bg-[#F2F2F4] hover:text-[#111113] shadow-xs active:scale-95'
                : 'text-[#B0B0B8] border-transparent cursor-not-allowed opacity-40'
            }`}
          >
            <ChevronLeft className="w-4 h-4 stroke-[2.2]" />
            <span className="hidden sm:inline">Back</span>
          </button>

          {/* Play / Pause Toggle */}
          <button
            type="button"
            onClick={isPlaying ? onPause : onPlay}
            disabled={!hasSteps}
            data-cursor="button"
            title={isPlaying ? 'Pause (Space)' : 'Play dry run (Space)'}
            className={`flex items-center gap-1.5 px-4 py-1.5 rounded-xl text-xs font-semibold transition-all cursor-pointer shadow-sm active:scale-95 ${
              hasSteps
                ? isPlaying
                  ? 'bg-amber-600 text-white hover:bg-amber-700'
                  : 'bg-[#111113] text-white hover:bg-black'
                : 'bg-black/10 text-[#8A8A90] cursor-not-allowed opacity-40'
            }`}
          >
            {isPlaying ? (
              <>
                <Pause className="w-3.5 h-3.5 fill-current" />
                <span>Pause</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Play</span>
              </>
            )}
          </button>

          {/* Next Step */}
          <button
            type="button"
            onClick={onNext}
            disabled={!canGoNext}
            data-cursor="button"
            title="Next step (Right Arrow)"
            className={`flex items-center gap-1 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer ${
              canGoNext
                ? 'bg-[#6C5CFF]/10 text-[#5542F6] border-[#6C5CFF]/30 hover:bg-[#6C5CFF]/20 shadow-xs active:scale-95'
                : 'text-[#B0B0B8] border-transparent cursor-not-allowed opacity-40'
            }`}
          >
            <span className="hidden sm:inline">Next</span>
            <ChevronRight className="w-4 h-4 stroke-[2.2]" />
          </button>
        </div>

        {/* Speed Selector */}
        <div className="flex items-center gap-1.5">
          <div className="flex items-center gap-1 bg-black/[0.04] p-0.5 rounded-xl border border-black/[0.04]">
            {SPEED_OPTIONS.map((opt) => {
              const active = playSpeedMs === opt.ms;
              return (
                <button
                  key={opt.label}
                  type="button"
                  onClick={() => onSetPlaySpeedMs(opt.ms)}
                  data-cursor="button"
                  className={`px-2 py-0.5 rounded-lg text-[11px] font-semibold transition-all cursor-pointer ${
                    active
                      ? 'bg-white text-[#111113] shadow-2xs'
                      : 'text-[#6B6B73] hover:text-[#111113]'
                  }`}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
