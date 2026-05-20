'use client';

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { ChatSession, ChatMessage } from '@/lib/types';
import { generateId } from '@/lib/utils';

interface ChatStore {
  sessions: ChatSession[];
  currentSessionId: string | null;
  isSearching: boolean;
  streamingMessageId: string | null;

  // Actions
  createSession: () => string;
  setCurrentSession: (id: string) => void;
  deleteSession: (id: string) => void;
  addMessage: (sessionId: string, message: ChatMessage) => void;
  updateMessage: (
    sessionId: string,
    messageId: string,
    updates: Partial<ChatMessage>
  ) => void;
  setIsSearching: (val: boolean) => void;
  setStreamingMessageId: (id: string | null) => void;
  getCurrentSession: () => ChatSession | null;
}

export const useChatStore = create<ChatStore>()(
  persist(
    (set, get) => ({
      sessions: [],
      currentSessionId: null,
      isSearching: false,
      streamingMessageId: null,

      createSession: () => {
        const id = generateId();
        const newSession: ChatSession = {
          id,
          title: 'New Chat',
          messages: [],
          createdAt: new Date(),
        };
        set((state) => ({
          sessions: [newSession, ...state.sessions],
          currentSessionId: id,
        }));
        return id;
      },

      setCurrentSession: (id: string) => {
        set({ currentSessionId: id });
      },

      deleteSession: (id: string) => {
        set((state) => {
          const remaining = state.sessions.filter((s) => s.id !== id);
          let nextId = state.currentSessionId;

          if (state.currentSessionId === id) {
            nextId = remaining.length > 0 ? remaining[0].id : null;
          }

          return { sessions: remaining, currentSessionId: nextId };
        });
      },

      addMessage: (sessionId: string, message: ChatMessage) => {
        set((state) => ({
          sessions: state.sessions.map((session) => {
            if (session.id !== sessionId) return session;

            // Auto-set title from first user message
            const title =
              session.messages.length === 0 && message.type === 'user' && message.query
                ? message.query.slice(0, 40)
                : session.title;

            return {
              ...session,
              title,
              messages: [...session.messages, message],
            };
          }),
        }));
      },

      updateMessage: (
        sessionId: string,
        messageId: string,
        updates: Partial<ChatMessage>
      ) => {
        set((state) => ({
          sessions: state.sessions.map((session) => {
            if (session.id !== sessionId) return session;
            return {
              ...session,
              messages: session.messages.map((msg) =>
                msg.id === messageId ? { ...msg, ...updates } : msg
              ),
            };
          }),
        }));
      },

      setIsSearching: (val: boolean) => {
        set({ isSearching: val });
      },

      setStreamingMessageId: (id: string | null) => {
        set({ streamingMessageId: id });
      },

      getCurrentSession: () => {
        const { sessions, currentSessionId } = get();
        return sessions.find((s) => s.id === currentSessionId) ?? null;
      },
    }),
    {
      name: 'locallens-chat-storage',
      storage: createJSONStorage(() => localStorage),
      // Revive Date objects after JSON deserialization
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        state.sessions = state.sessions.map((s) => ({
          ...s,
          createdAt: new Date(s.createdAt),
          messages: s.messages.map((m) => ({
            ...m,
            timestamp: new Date(m.timestamp),
          })),
        }));

        // Ensure there is always a session to work with
        if (state.sessions.length === 0) {
          const id = generateId();
          state.sessions = [
            { id, title: 'New Chat', messages: [], createdAt: new Date() },
          ];
          state.currentSessionId = id;
        } else if (!state.currentSessionId) {
          state.currentSessionId = state.sessions[0].id;
        }
      },
    }
  )
);

// Auto-create first session if none exist (runs once on module load in browser)
if (typeof window !== 'undefined') {
  // Give the persist middleware a tick to rehydrate
  setTimeout(() => {
    const { sessions, currentSessionId, createSession } = useChatStore.getState();
    if (sessions.length === 0 || !currentSessionId) {
      createSession();
    }
  }, 0);
}
