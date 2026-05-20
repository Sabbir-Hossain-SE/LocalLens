import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function getScoreColor(score: number): string {
  if (score >= 75) return '#10b981';
  if (score >= 50) return '#f59e0b';
  return '#ef4444';
}

export function getScoreLabel(score: number): string {
  if (score >= 80) return 'Excellent';
  if (score >= 65) return 'Good';
  if (score >= 50) return 'Fair';
  return 'Poor';
}

export function truncateText(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 3) + '...';
}

export function formatSessionTitle(query: string): string {
  return truncateText(query, 40);
}

export function formatTimestamp(date: Date): string {
  const now = new Date();
  const diff = now.getTime() - new Date(date).getTime();
  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return new Date(date).toLocaleDateString();
}

export function getPipelineStepLabel(step: string): string {
  const labels: Record<string, string> = {
    intent_parsed: 'Intent Parser',
    location_resolved: 'Location',
    search_complete: 'Search & Crawl',
    reviews_aggregated: 'Review Analysis',
    scoring_complete: 'Scoring',
    summary_ready: 'Summarizing',
    done: 'Done',
  };
  return labels[step] || step;
}

export function getPipelineStepIcon(step: string): string {
  const icons: Record<string, string> = {
    intent_parsed: '🧠',
    location_resolved: '📍',
    search_complete: '🔍',
    reviews_aggregated: '⭐',
    scoring_complete: '📊',
    summary_ready: '✍️',
    done: '✅',
  };
  return icons[step] || '⚙️';
}
