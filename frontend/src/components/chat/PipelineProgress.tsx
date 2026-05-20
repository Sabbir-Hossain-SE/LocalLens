'use client';

import { Check, Loader2, X, Circle } from 'lucide-react';
import type { PipelineStep } from '@/lib/types';
import { getPipelineStepLabel, getPipelineStepIcon } from '@/lib/utils';
import { cn } from '@/lib/utils';

interface PipelineProgressProps {
  steps: PipelineStep[];
}

function StepIcon({ status }: { status: PipelineStep['status'] }) {
  if (status === 'done')
    return (
      <span className="flex items-center justify-center w-5 h-5 rounded-full bg-brand text-white">
        <Check size={11} strokeWidth={3} />
      </span>
    );
  if (status === 'running')
    return (
      <span className="flex items-center justify-center w-5 h-5 rounded-full bg-brand/20 text-brand">
        <Loader2 size={12} className="animate-spin" />
      </span>
    );
  if (status === 'error')
    return (
      <span className="flex items-center justify-center w-5 h-5 rounded-full bg-red-900 text-red-400">
        <X size={11} strokeWidth={3} />
      </span>
    );
  return (
    <span className="flex items-center justify-center w-5 h-5 rounded-full bg-surface-DEFAULT border border-surface-border text-slate-600">
      <Circle size={8} fill="currentColor" />
    </span>
  );
}

export default function PipelineProgress({ steps }: PipelineProgressProps) {
  console.log('[PipelineProgress] render with steps:', steps.map(s => `${s.step}:${s.status}`).join(', '));
  const doneCount = steps.filter((s) => s.status === 'done').length;
  const progressPct = Math.round((doneCount / steps.length) * 100);

  return (
    <div className="w-full animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Loader2 size={14} className="animate-spin text-brand" />
          <span className="text-sm font-medium text-slate-300">Analyzing your request…</span>
        </div>
        <span className="text-xs text-slate-500">{progressPct}%</span>
      </div>

      {/* Progress bar */}
      <div className="h-1 w-full bg-surface-border rounded-full mb-4 overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-brand to-brand-light rounded-full transition-all duration-500 ease-out"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Step list */}
      <div className="flex flex-col gap-2">
        {steps.map((step, index) => (
          <div
            key={step.step}
            className={cn(
              'flex items-start gap-3 px-3 py-2.5 rounded-xl transition-all duration-300',
              step.status === 'running' && 'bg-brand/5 border border-brand/20',
              step.status === 'done' && 'opacity-70',
              step.status === 'pending' && 'opacity-40'
            )}
            style={{
              animationDelay: `${index * 50}ms`,
            }}
          >
            <div className="flex-shrink-0 mt-0.5">
              <StepIcon status={step.status} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-base leading-none">
                  {getPipelineStepIcon(step.step)}
                </span>
                <span
                  className={cn(
                    'text-sm font-medium',
                    step.status === 'done' && 'text-slate-400',
                    step.status === 'running' && 'text-slate-200',
                    step.status === 'pending' && 'text-slate-600',
                    step.status === 'error' && 'text-red-400'
                  )}
                >
                  {getPipelineStepLabel(step.step)}
                </span>
                {step.status === 'running' && (
                  <span className="text-xs text-brand animate-pulse">In progress</span>
                )}
              </div>
              {step.detail && (
                <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{step.detail}</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
