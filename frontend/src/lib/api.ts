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

export interface PrevTurn {
  query: string;
  category?: string;
  location?: string;
}

// Uses the browser's native EventSource API instead of fetch+ReadableStream.
// EventSource is purpose-built for SSE and avoids the fetch reader buffering
// that prevents events from being delivered to JavaScript in real time.
export function searchStream(
  query: string,
  userIp?: string,
  prev?: PrevTurn
): AsyncGenerator<StreamEvent> {
  const params = new URLSearchParams({ query });
  if (userIp) params.set('user_ip', userIp);
  if (prev?.query) {
    params.set('prev_query', prev.query);
    if (prev.category) params.set('prev_category', prev.category);
    if (prev.location) params.set('prev_location', prev.location);
  }
  const url = `${API_BASE}/search/stream?${params.toString()}`;

  const queue: StreamEvent[] = [];
  let resolveNext: (() => void) | null = null;
  let finished = false;
  let streamError: Error | null = null;

  const source = new EventSource(url);

  const wake = () => {
    if (resolveNext) {
      const r = resolveNext;
      resolveNext = null;
      r();
    }
  };

  const handleMessage = (eventType: string) => (e: MessageEvent) => {
    try {
      const parsed = JSON.parse(e.data) as StreamEvent;
      if (!parsed.event) {
        (parsed as StreamEvent & { event: string }).event =
          eventType as StreamEvent['event'];
      }
      queue.push(parsed);
      wake();
    } catch (err) {
      console.warn('[searchStream] failed to parse SSE chunk:', e.data, err);
    }
  };

  const EVENT_TYPES = [
    'intent_parsed',
    'location_resolved',
    'search_complete',
    'reviews_aggregated',
    'scoring_complete',
    'summary_ready',
    'done',
    'error',
  ];
  for (const t of EVENT_TYPES) {
    source.addEventListener(t, handleMessage(t) as EventListener);
  }

  source.onerror = () => {
    // EventSource also fires onerror on normal close. Only treat as error
    // if we haven't seen a 'done' or 'error' event yet.
    if (!finished) {
      streamError = new Error('SSE connection error');
      finished = true;
      wake();
    }
  };

  async function* generator(): AsyncGenerator<StreamEvent> {
    try {
      while (true) {
        if (queue.length > 0) {
          const ev = queue.shift()!;
          yield ev;
          if (ev.event === 'done' || ev.event === 'error') {
            finished = true;
            return;
          }
        } else if (finished) {
          if (streamError) throw streamError;
          return;
        } else {
          await new Promise<void>((resolve) => {
            resolveNext = resolve;
          });
        }
      }
    } finally {
      source.close();
    }
  }

  return generator();
}

export async function getHealth(): Promise<{ status: string; version: string }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json() as Promise<{ status: string; version: string }>;
}

export async function transcribe(blob: Blob, filename = 'audio.webm'): Promise<string> {
  const form = new FormData();
  form.append('audio', blob, filename);
  const res = await fetch(`${API_BASE}/transcribe`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Transcription failed (${res.status}): ${text}`);
  }
  const data = (await res.json()) as { text: string };
  return data.text ?? '';
}
