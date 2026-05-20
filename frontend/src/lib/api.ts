import type { SearchResponse, StreamEvent } from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function search(query: string, userIp?: string): Promise<SearchResponse> {
  const params = new URLSearchParams({ query });
  if (userIp) params.set('user_ip', userIp);

  const res = await fetch(`${API_BASE}/search?${params.toString()}`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Search failed (${res.status}): ${text}`);
  }

  return res.json() as Promise<SearchResponse>;
}

export async function* searchStream(
  query: string,
  userIp?: string
): AsyncGenerator<StreamEvent> {
  const params = new URLSearchParams({ query });
  if (userIp) params.set('user_ip', userIp);

  const res = await fetch(`${API_BASE}/search/stream?${params.toString()}`, {
    method: 'GET',
    headers: { Accept: 'text/event-stream', 'Cache-Control': 'no-cache' },
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Stream failed (${res.status}): ${text}`);
  }

  if (!res.body) {
    throw new Error('No response body for SSE stream');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE messages are separated by double newlines
      const parts = buffer.split('\n\n');
      // Keep the last incomplete chunk in the buffer
      buffer = parts.pop() ?? '';

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;

        // Parse SSE fields
        let eventType = '';
        let dataStr = '';

        for (const line of trimmed.split('\n')) {
          if (line.startsWith('event:')) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            dataStr = line.slice(5).trim();
          }
        }

        if (!dataStr) continue;

        try {
          const parsed = JSON.parse(dataStr) as StreamEvent;
          // If the SSE event field was set, use it; otherwise trust parsed.event
          if (eventType && !parsed.event) {
            (parsed as StreamEvent & { event: string }).event = eventType as StreamEvent['event'];
          }
          yield parsed;
        } catch {
          // Ignore malformed JSON chunks
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function getHealth(): Promise<{ status: string; version: string }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json() as Promise<{ status: string; version: string }>;
}
