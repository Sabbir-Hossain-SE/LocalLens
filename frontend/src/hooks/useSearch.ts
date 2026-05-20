'use client';

import { useCallback } from 'react';
import { useChatStore } from '@/store/chatStore';
import { searchStream } from '@/lib/api';
import { generateId } from '@/lib/utils';
import type { ChatMessage, PipelineStep, SearchResponse } from '@/lib/types';

const PIPELINE_STEPS_ORDER = [
  'intent_parsed',
  'location_resolved',
  'search_complete',
  'reviews_aggregated',
  'scoring_complete',
  'summary_ready',
];

function buildInitialSteps(): PipelineStep[] {
  return PIPELINE_STEPS_ORDER.map((step) => ({
    step,
    status: 'pending' as const,
  }));
}

export function useSearch() {
  const {
    currentSessionId,
    createSession,
    addMessage,
    updateMessage,
    setIsSearching,
    setStreamingMessageId,
    isSearching,
  } = useChatStore();

  const submitQuery = useCallback(
    async (query: string) => {
      if (!query.trim() || isSearching) return;

      // Ensure we have a session
      let sessionId = currentSessionId;
      if (!sessionId) {
        sessionId = createSession();
      }

      setIsSearching(true);

      // 1. Add user message immediately
      const userMsg: ChatMessage = {
        id: generateId(),
        type: 'user',
        query: query.trim(),
        timestamp: new Date(),
      };
      addMessage(sessionId, userMsg);

      // 2. Add streaming assistant message placeholder
      const assistantMsgId = generateId();
      const assistantMsg: ChatMessage = {
        id: assistantMsgId,
        type: 'assistant',
        isStreaming: true,
        pipelineSteps: buildInitialSteps(),
        timestamp: new Date(),
      };
      addMessage(sessionId, assistantMsg);
      setStreamingMessageId(assistantMsgId);

      try {
        const generator = searchStream(query.trim());

        for await (const event of generator) {
          const { event: eventType, data } = event;

          if (eventType === 'error') {
            const errMsg = typeof data.detail === 'string' ? data.detail : 'An error occurred';
            updateMessage(sessionId, assistantMsgId, {
              isStreaming: false,
              type: 'error',
              errorMessage: errMsg,
              pipelineSteps: undefined,
            });
            break;
          }

          // Mark the corresponding step as done and activate next
          if (eventType !== 'done') {
            updateMessage(sessionId, assistantMsgId, {
              pipelineSteps: (() => {
                const steps = buildInitialSteps();
                const stepIndex = PIPELINE_STEPS_ORDER.indexOf(eventType);
                if (stepIndex === -1) return steps;

                return steps.map((s, i) => {
                  if (i < stepIndex) return { ...s, status: 'done' as const };
                  if (i === stepIndex) {
                    let detail: string | undefined;
                    if (eventType === 'intent_parsed' && data.category) {
                      detail = `${data.category}${data.count ? `, ${data.count} results` : ''}${data.location ? `, near ${data.location}` : ''}`;
                    } else if (eventType === 'location_resolved' && data.location) {
                      detail = String(data.location);
                    } else if (eventType === 'search_complete' && data.total !== undefined) {
                      detail = `Found ${data.total} businesses`;
                    } else if (eventType === 'reviews_aggregated') {
                      detail = 'Reviews analyzed';
                    } else if (eventType === 'scoring_complete') {
                      detail = 'Businesses ranked';
                    } else if (eventType === 'summary_ready') {
                      detail = 'Summaries generated';
                    }
                    return { ...s, status: 'done' as const, detail };
                  }
                  // Next step is running
                  if (i === stepIndex + 1)
                    return { ...s, status: 'running' as const };
                  return s;
                });
              })(),
            });
          }

          // When the final done event arrives with the full result
          if (eventType === 'done' && data) {
            const response = data as unknown as SearchResponse;
            updateMessage(sessionId, assistantMsgId, {
              isStreaming: false,
              response,
              pipelineSteps: PIPELINE_STEPS_ORDER.map((step) => ({
                step,
                status: 'done' as const,
              })),
            });
          }
        }
      } catch (err) {
        const errorMsg =
          err instanceof Error ? err.message : 'Unknown error occurred';

        const isConnectionError =
          errorMsg.includes('fetch') ||
          errorMsg.includes('Failed to fetch') ||
          errorMsg.includes('ECONNREFUSED');

        const displayError = isConnectionError
          ? 'Cannot connect to backend. Make sure it is running:\n\ncd backend && uvicorn app.main:app --reload'
          : errorMsg;

        updateMessage(sessionId, assistantMsgId, {
          isStreaming: false,
          type: 'error',
          errorMessage: displayError,
          pipelineSteps: undefined,
        });
      } finally {
        setIsSearching(false);
        setStreamingMessageId(null);
      }
    },
    [
      currentSessionId,
      isSearching,
      createSession,
      addMessage,
      updateMessage,
      setIsSearching,
      setStreamingMessageId,
    ]
  );

  return { submitQuery, isSearching };
}
