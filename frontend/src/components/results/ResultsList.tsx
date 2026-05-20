'use client';

import { MapPin, Clock, Search } from 'lucide-react';
import type { SearchResponse } from '@/lib/types';
import ResultCard from './ResultCard';
import { formatElapsed } from '@/lib/utils';

interface ResultsListProps {
  response: SearchResponse;
}

export default function ResultsList({ response }: ResultsListProps) {
  const { results, total_results, elapsed_ms, location, query } = response;

  return (
    <div className="w-full animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4 px-1">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-brand animate-pulse" />
          <span className="text-slate-300 font-semibold text-sm">
            {total_results} result{total_results !== 1 ? 's' : ''}
          </span>
        </div>
        <span className="text-slate-600">·</span>
        <div className="flex items-center gap-1 text-slate-500 text-xs">
          <Clock size={11} />
          <span>{formatElapsed(elapsed_ms)}</span>
        </div>
        {location && (
          <>
            <span className="text-slate-600">·</span>
            <div className="flex items-center gap-1 text-slate-500 text-xs">
              <MapPin size={11} />
              <span>{location}</span>
            </div>
          </>
        )}
      </div>

      {/* Query echo */}
      <div className="mb-4 px-1">
        <p className="text-xs text-slate-500 italic">
          Showing results for: <span className="text-slate-400 not-italic">"{query}"</span>
        </p>
      </div>

      {/* Results */}
      {results.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-surface-card border border-surface-border flex items-center justify-center mb-4">
            <Search size={28} className="text-slate-600" />
          </div>
          <h3 className="text-slate-300 font-semibold mb-2">No results found</h3>
          <p className="text-slate-500 text-sm max-w-xs">
            Try broadening your search area, adjusting the category, or using a different location.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {results.map((business, index) => (
            <ResultCard
              key={business.id}
              business={business}
              animationDelay={index * 60}
            />
          ))}
        </div>
      )}
    </div>
  );
}
