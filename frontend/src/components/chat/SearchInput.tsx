'use client';

import { useState, useRef, useCallback, useEffect, KeyboardEvent } from 'react';
import { Send, Loader2, MapPin } from 'lucide-react';
import { cn } from '@/lib/utils';

interface SearchInputProps {
  onSubmit: (query: string) => void;
  isLoading?: boolean;
  placeholder?: string;
  initialValue?: string;
  onInitialValueConsumed?: () => void;
}

export default function SearchInput({
  onSubmit,
  isLoading = false,
  placeholder = 'Ask LocalLens anything… "Best ramen near downtown Seattle"',
  initialValue = '',
  onInitialValueConsumed,
}: SearchInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Allow parent to inject a value (e.g., clicking suggested query)
  useEffect(() => {
    if (initialValue) {
      setValue(initialValue);
      onInitialValueConsumed?.();
      textareaRef.current?.focus();
    }
  }, [initialValue, onInitialValueConsumed]);

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isLoading) return;
    onSubmit(trimmed);
    setValue('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, isLoading, onSubmit]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    // Auto-resize
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
  };

  return (
    <div className="relative">
      {/* Gradient fade above input */}
      <div className="absolute -top-8 left-0 right-0 h-8 bg-gradient-to-t from-surface-deep to-transparent pointer-events-none" />

      <div
        className={cn(
          'flex items-end gap-3 p-3 rounded-2xl',
          'bg-surface-card border border-surface-border',
          'focus-within:border-brand/60 focus-within:shadow-lg focus-within:shadow-brand/10',
          'transition-all duration-200',
          isLoading && 'opacity-80'
        )}
      >
        <div className="flex items-center gap-2 px-1 py-1 text-brand flex-shrink-0 self-end mb-1">
          <MapPin size={16} />
        </div>

        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isLoading}
          rows={1}
          className={cn(
            'flex-1 bg-transparent text-slate-100 placeholder-slate-600 text-sm',
            'resize-none outline-none leading-relaxed',
            'min-h-[36px] max-h-[160px] py-1.5',
            'disabled:cursor-not-allowed'
          )}
        />

        <button
          onClick={handleSubmit}
          disabled={!value.trim() || isLoading}
          className={cn(
            'flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center',
            'transition-all duration-200',
            value.trim() && !isLoading
              ? 'bg-brand hover:bg-brand-dark text-white shadow-md shadow-brand/30 hover:scale-105 active:scale-95'
              : 'bg-surface-DEFAULT text-slate-600 cursor-not-allowed'
          )}
          aria-label="Send message"
        >
          {isLoading ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Send size={15} />
          )}
        </button>
      </div>

      <p className="text-center text-xs text-slate-700 mt-2">
        Press Enter to search · Shift+Enter for new line
      </p>
    </div>
  );
}
