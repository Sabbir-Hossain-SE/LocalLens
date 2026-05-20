'use client';

import { useState } from 'react';
import { Plus, Trash2, MessageSquare, MapPin } from 'lucide-react';
import { useChatStore } from '@/store/chatStore';
import { formatTimestamp } from '@/lib/utils';
import { cn } from '@/lib/utils';

export default function Sidebar() {
  const { sessions, currentSessionId, createSession, setCurrentSession, deleteSession } =
    useChatStore();
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const handleNewChat = () => {
    createSession();
  };

  const handleDeleteSession = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    deleteSession(id);
  };

  return (
    <aside className="flex flex-col h-full w-64 bg-surface-DEFAULT border-r border-surface-border">
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5 border-b border-surface-border">
        <div className="w-8 h-8 rounded-xl bg-brand/20 border border-brand/30 flex items-center justify-center flex-shrink-0">
          <MapPin size={16} className="text-brand" />
        </div>
        <div>
          <h1 className="text-slate-100 font-bold text-lg leading-none">
            Local<span className="text-brand">Lens</span>
          </h1>
          <p className="text-slate-600 text-xs mt-0.5">AI Local Discovery</p>
        </div>
      </div>

      {/* New Chat button */}
      <div className="px-3 py-3">
        <button
          onClick={handleNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
                     bg-brand/10 border border-brand/30 text-brand text-sm font-medium
                     hover:bg-brand/20 hover:border-brand/50 transition-all duration-200
                     active:scale-[0.98]"
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>

      {/* Chat history label */}
      {sessions.length > 0 && (
        <div className="px-4 py-1">
          <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
            Recent Chats
          </span>
        </div>
      )}

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5 scrollbar-thin">
        {sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center px-3">
            <MessageSquare size={24} className="text-slate-700 mb-2" />
            <p className="text-slate-600 text-xs">No chats yet. Start searching!</p>
          </div>
        ) : (
          sessions.map((session) => {
            const isActive = session.id === currentSessionId;
            const isHovered = hoveredId === session.id;
            const firstUserMsg = session.messages.find((m) => m.type === 'user');
            const title = firstUserMsg?.query ?? session.title;
            const msgCount = session.messages.filter((m) => m.type === 'user').length;

            return (
              <div
                key={session.id}
                onClick={() => setCurrentSession(session.id)}
                onMouseEnter={() => setHoveredId(session.id)}
                onMouseLeave={() => setHoveredId(null)}
                className={cn(
                  'group relative flex items-start gap-2 px-3 py-2.5 rounded-xl cursor-pointer',
                  'transition-all duration-150',
                  isActive
                    ? 'bg-brand/10 border border-brand/20 text-slate-200'
                    : 'hover:bg-surface-card text-slate-400 hover:text-slate-200 border border-transparent'
                )}
              >
                <MessageSquare
                  size={13}
                  className={cn(
                    'flex-shrink-0 mt-0.5',
                    isActive ? 'text-brand' : 'text-slate-600'
                  )}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate leading-relaxed">{title}</p>
                  <p className="text-xs text-slate-600 mt-0.5">
                    {msgCount > 0
                      ? `${msgCount} search${msgCount !== 1 ? 'es' : ''} · ${formatTimestamp(session.createdAt)}`
                      : formatTimestamp(session.createdAt)}
                  </p>
                </div>

                {/* Delete button */}
                {isHovered && (
                  <button
                    onClick={(e) => handleDeleteSession(e, session.id)}
                    className="flex-shrink-0 w-5 h-5 rounded-md flex items-center justify-center
                               text-slate-600 hover:text-red-400 hover:bg-red-900/30 transition-colors"
                    aria-label="Delete chat"
                  >
                    <Trash2 size={11} />
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-4 border-t border-surface-border">
        <p className="text-xs text-slate-700 text-center">
          Powered by{' '}
          <span className="text-slate-500">OSM</span>
          {' · '}
          <span className="text-slate-500">DuckDuckGo</span>
          {' · '}
          <span className="text-brand/70">AI</span>
        </p>
      </div>
    </aside>
  );
}
