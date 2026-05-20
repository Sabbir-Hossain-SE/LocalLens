'use client';

import { formatTimestamp } from '@/lib/utils';

interface UserMessageProps {
  query: string;
  timestamp: Date;
}

export default function UserMessage({ query, timestamp }: UserMessageProps) {
  return (
    <div className="flex justify-end animate-slide-up">
      <div className="max-w-[75%] flex flex-col items-end gap-1">
        <div
          className="px-4 py-3 rounded-2xl rounded-br-sm
                     bg-gradient-to-br from-brand to-brand-dark
                     text-white font-medium text-sm leading-relaxed
                     shadow-lg shadow-brand/20"
        >
          {query}
        </div>
        <span className="text-xs text-slate-600 px-1">{formatTimestamp(timestamp)}</span>
      </div>
    </div>
  );
}
