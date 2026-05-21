'use client';

import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Activity, Bot, Database, Mic, Gauge, AlertCircle } from 'lucide-react';
import { getHealth, getMetrics } from '@/lib/api';
import type { HealthResponse, MetricsResponse } from '@/lib/types';
import { formatElapsed } from '@/lib/utils';

function StatusRow({
  icon,
  label,
  value,
  ok = true,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  ok?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-2 border-b border-surface-border/60 last:border-b-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className={ok ? 'text-brand' : 'text-amber-400'}>{icon}</span>
        <span className="text-xs text-slate-500">{label}</span>
      </div>
      <span className="text-xs text-slate-300 truncate text-right">{value}</span>
    </div>
  );
}

export default function SystemStatusPanel() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [h, m] = await Promise.all([getHealth(), getMetrics()]);
        if (!cancelled) {
          setHealth(h);
          setMetrics(m);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Backend unavailable');
        }
      }
    }

    load();
    const id = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return (
    <div className="flex flex-col h-full bg-surface-DEFAULT">
      <div className="px-4 py-4 border-b border-surface-border">
        <div className="flex items-center gap-2 mb-1">
          <Activity size={16} className="text-brand" />
          <h2 className="text-slate-200 font-semibold text-sm">Runtime Status</h2>
        </div>
        <p className="text-xs text-slate-600 leading-relaxed">
          Backend features available to LocalLens.
        </p>
      </div>

      <div className="p-4 space-y-4 overflow-y-auto scrollbar-thin">
        {error && (
          <div className="rounded-lg border border-red-800/60 bg-red-950/40 p-3 text-xs text-red-300">
            <div className="flex items-center gap-2 mb-1">
              <AlertCircle size={14} />
              <span className="font-semibold">Backend offline</span>
            </div>
            {error}
          </div>
        )}

        <div className="rounded-lg border border-surface-border bg-surface-card/50 px-3">
          <StatusRow
            icon={<Bot size={14} />}
            label="LLM"
            value={health ? `${health.llm_provider} · ${health.llm_model}` : 'Checking'}
            ok={health?.llm_reachable ?? false}
          />
          <StatusRow
            icon={<Mic size={14} />}
            label="Voice"
            value={health?.voice_transcription?.configured ? 'Remote Whisper' : 'Not configured'}
            ok={Boolean(health?.voice_transcription?.configured)}
          />
          <StatusRow
            icon={<Database size={14} />}
            label="Cache"
            value={health?.cache_status ? `${health.cache_status.entries} entries` : 'Checking'}
            ok
          />
          <StatusRow
            icon={<Gauge size={14} />}
            label="Avg latency"
            value={metrics ? formatElapsed(Math.round(metrics.avg_latency_ms)) : 'No data'}
            ok={(metrics?.errors ?? 0) === 0}
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-lg border border-surface-border bg-surface-card/50 p-3">
            <div className="text-lg font-semibold text-slate-200">
              {metrics?.total_queries ?? 0}
            </div>
            <div className="text-[11px] text-slate-600">queries</div>
          </div>
          <div className="rounded-lg border border-surface-border bg-surface-card/50 p-3">
            <div className="text-lg font-semibold text-slate-200">
              {metrics ? `${Math.round(metrics.cache_hit_rate * 100)}%` : '0%'}
            </div>
            <div className="text-[11px] text-slate-600">cache hits</div>
          </div>
        </div>

        <div className="rounded-lg border border-surface-border bg-surface-card/40 p-3">
          <div className="text-xs font-semibold text-slate-300 mb-2">Scope Coverage</div>
          <div className="space-y-1.5 text-xs">
            {[
              'Intent parsing',
              'Location resolution',
              'Multi-source search',
              'Review sentiment',
              'Weighted scoring',
              'LLM summaries',
              'Voice transcription',
              'Runtime metrics',
            ].map((item) => (
              <div key={item} className="flex items-center gap-2 text-slate-500">
                <span className="w-1.5 h-1.5 rounded-full bg-brand" />
                {item}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
