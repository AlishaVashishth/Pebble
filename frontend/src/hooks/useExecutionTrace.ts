/**
 * Hook for managing execution trace step-by-step navigation,
 * play/pause playback loop, and current step index.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { TraceStep } from '../lib/playground.ts';

export interface UseExecutionTraceReturn {
  steps: TraceStep[];
  currentStepIndex: number;
  currentStep: TraceStep | null;
  totalSteps: number;
  isPlaying: boolean;
  playSpeedMs: number;
  setPlaySpeedMs: (speed: number) => void;
  setSteps: (steps: TraceStep[]) => void;
  goNext: () => void;
  goPrev: () => void;
  play: () => void;
  pause: () => void;
  reset: () => void;
  jumpToStep: (index: number) => void;
}

export function useExecutionTrace(
  initialSteps: TraceStep[] = [],
  initialSpeedMs: number = 1200
): UseExecutionTraceReturn {
  const [steps, setStepsState] = useState<TraceStep[]>(initialSteps);
  const [currentStepIndex, setCurrentStepIndex] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [playSpeedMs, setPlaySpeedMs] = useState<number>(initialSpeedMs);

  const timerRef = useRef<NodeJS.Timeout | null>(null);

  const totalSteps = steps.length;
  const currentStep = totalSteps > 0 && currentStepIndex >= 0 && currentStepIndex < totalSteps
    ? steps[currentStepIndex]
    : null;

  const pause = useCallback(() => {
    setIsPlaying(false);
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const goNext = useCallback(() => {
    setCurrentStepIndex((prev) => {
      if (prev < totalSteps - 1) {
        return prev + 1;
      }
      pause();
      return prev;
    });
  }, [totalSteps, pause]);

  const goPrev = useCallback(() => {
    setCurrentStepIndex((prev) => Math.max(0, prev - 1));
  }, []);

  const reset = useCallback(() => {
    pause();
    setCurrentStepIndex(0);
  }, [pause]);

  const play = useCallback(() => {
    if (totalSteps === 0) return;
    // If at the end, wrap around to start
    setCurrentStepIndex((prev) => (prev >= totalSteps - 1 ? 0 : prev));
    setIsPlaying(true);
  }, [totalSteps]);

  const jumpToStep = useCallback(
    (index: number) => {
      if (index >= 0 && index < totalSteps) {
        setCurrentStepIndex(index);
      }
    },
    [totalSteps]
  );

  const setSteps = useCallback((newSteps: TraceStep[]) => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setIsPlaying(false);
    setStepsState(newSteps);
    setCurrentStepIndex(0);
  }, []);

  // Playback timer effect
  useEffect(() => {
    if (!isPlaying) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    timerRef.current = setInterval(() => {
      setCurrentStepIndex((prev) => {
        if (prev < totalSteps - 1) {
          return prev + 1;
        } else {
          // Reached end of trace
          setIsPlaying(false);
          return prev;
        }
      });
    }, playSpeedMs);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [isPlaying, playSpeedMs, totalSteps]);

  return {
    steps,
    currentStepIndex,
    currentStep,
    totalSteps,
    isPlaying,
    playSpeedMs,
    setPlaySpeedMs,
    setSteps,
    goNext,
    goPrev,
    play,
    pause,
    reset,
    jumpToStep,
  };
}
