'use client';

import { HelpCircle } from 'lucide-react';
import type { ClarificationPayload } from '@/lib/types';

interface ClarificationPromptProps {
  payload: ClarificationPayload;
  onPick: (answer: string) => void;
}

/**
 * Rendered when the backend emits a `clarification_needed` SSE event.
 * Shows the agent's question + clickable option chips; picking one
 * submits a new query that includes the user's choice.
 */
export default function ClarificationPrompt({ payload, onPick }: ClarificationPromptProps) {
  return (
    <div className="w-full animate-fade-in">
      <div className="flex items-center gap-2 mb-3">
        <HelpCircle size={14} className="text-brand" />
        <span className="text-sm font-medium text-slate-300">{payload.question}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {payload.options.map((opt) => (
          <button
            key={opt}
            onClick={() => onPick(opt)}
            className="px-3 py-1.5 rounded-full text-sm
                       bg-surface-card border border-surface-border
                       text-slate-300 hover:border-brand/50 hover:bg-surface-hover hover:text-slate-100
                       transition-all duration-150"
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}
