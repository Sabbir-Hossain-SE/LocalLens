'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertCircle, Terminal } from 'lucide-react';
import { useChatStore } from '@/store/chatStore';
import { useSearch } from '@/hooks/useSearch';
import UserMessage from './UserMessage';
import SearchInput from './SearchInput';
import PipelineProgress from './PipelineProgress';
import ResultsList from '@/components/results/ResultsList';

const SUGGESTED_QUERIES = [
  'Best sushi restaurants near me',
  'Coffee shops in downtown Austin',
  'Top dentists near zip 10001',
  'Yoga studios in Seattle',
];

const LOCALLENS_LOGO = (
  <svg
    width="40"
    height="40"
    viewBox="0 0 40 40"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className="flex-shrink-0"
  >
    <circle cx="20" cy="20" r="20" fill="#10b981" fillOpacity="0.15" />
    <circle cx="20" cy="20" r="8" stroke="#10b981" strokeWidth="2.5" fill="none" />
    <circle cx="20" cy="20" r="3" fill="#10b981" />
    <line x1="20" y1="6" x2="20" y2="12" stroke="#10b981" strokeWidth="2" strokeLinecap="round" />
    <line x1="20" y1="28" x2="20" y2="34" stroke="#10b981" strokeWidth="2" strokeLinecap="round" />
    <line x1="6" y1="20" x2="12" y2="20" stroke="#10b981" strokeWidth="2" strokeLinecap="round" />
    <line x1="28" y1="20" x2="34" y2="20" stroke="#10b981" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

export default function ChatArea() {
  const { getCurrentSession, isSearching } = useChatStore();
  const { submitQuery } = useSearch();
  const session = getCurrentSession();
  const messages = session?.messages ?? [];
  const bottomRef = useRef<HTMLDivElement>(null);
  const [suggestedQuery, setSuggestedQuery] = useState('');

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSuggestedQuery = (query: string) => {
    setSuggestedQuery(query);
  };

  const handleSubmit = (query: string) => {
    setSuggestedQuery('');
    submitQuery(query);
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6 scrollbar-thin">
        {isEmpty ? (
          /* Empty state */
          <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center px-4 animate-fade-in">
            <div className="mb-6">{LOCALLENS_LOGO}</div>
            <h1 className="text-3xl font-bold text-slate-100 mb-2">
              Local<span className="text-brand">Lens</span>
            </h1>
            <p className="text-slate-400 text-base mb-8 max-w-sm">
              Discover local gems with AI. Ask me to find the best restaurants,
              services, or any local business near you.
            </p>

            {/* Suggested queries */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-md">
              {SUGGESTED_QUERIES.map((q) => (
                <button
                  key={q}
                  onClick={() => handleSuggestedQuery(q)}
                  className="px-4 py-3 rounded-xl text-sm text-slate-300 text-left
                             bg-surface-card border border-surface-border
                             hover:border-brand/50 hover:bg-surface-hover hover:text-slate-100
                             transition-all duration-200 group"
                >
                  <span className="text-brand group-hover:text-brand-light mr-2 text-base">→</span>
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Message list */
          <>
            {messages.map((msg) => {
              if (msg.type === 'user') {
                return (
                  <UserMessage
                    key={msg.id}
                    query={msg.query ?? ''}
                    timestamp={msg.timestamp}
                  />
                );
              }

              if (msg.type === 'error') {
                return (
                  <div key={msg.id} className="flex justify-start animate-slide-up">
                    <div className="max-w-[85%] bg-red-950/60 border border-red-800/50 rounded-2xl rounded-bl-sm p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <AlertCircle size={16} className="text-red-400 flex-shrink-0" />
                        <span className="text-red-400 font-medium text-sm">Error</span>
                      </div>
                      <pre className="text-red-300 text-xs font-mono whitespace-pre-wrap leading-relaxed">
                        {msg.errorMessage}
                      </pre>
                      {msg.errorMessage?.includes('uvicorn') && (
                        <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
                          <Terminal size={12} />
                          <code className="text-slate-400">
                            cd backend && uvicorn app.main:app --reload
                          </code>
                        </div>
                      )}
                    </div>
                  </div>
                );
              }

              // Assistant message
              return (
                <div key={msg.id} className="flex justify-start animate-slide-up">
                  <div className="max-w-[90%] w-full">
                    {/* Avatar */}
                    <div className="flex items-center gap-2 mb-3">
                      <div className="w-7 h-7 rounded-lg bg-brand/20 border border-brand/30 flex items-center justify-center">
                        <div className="w-3 h-3 rounded-full bg-brand" />
                      </div>
                      <span className="text-xs font-medium text-slate-400">LocalLens AI</span>
                    </div>

                    <div className="bg-surface-card border border-surface-border rounded-2xl rounded-tl-sm p-4">
                      {msg.isStreaming && msg.pipelineSteps && (
                        <PipelineProgress steps={msg.pipelineSteps} />
                      )}

                      {!msg.isStreaming && msg.response && (
                        <ResultsList response={msg.response} />
                      )}

                      {!msg.isStreaming && !msg.response && (
                        <p className="text-slate-500 text-sm italic">No results returned.</p>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 px-4 pb-4 pt-2">
        <SearchInput
          onSubmit={handleSubmit}
          isLoading={isSearching}
          initialValue={suggestedQuery}
          onInitialValueConsumed={() => setSuggestedQuery('')}
        />
      </div>
    </div>
  );
}
