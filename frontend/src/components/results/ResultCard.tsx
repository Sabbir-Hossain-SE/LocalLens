'use client';

import { MapPin, Clock, ExternalLink, Phone, Globe, AlertTriangle, Star, ThumbsUp, Activity } from 'lucide-react';
import type { BusinessListing } from '@/lib/types';
import ScoreBadge from './ScoreBadge';
import { cn } from '@/lib/utils';

interface ResultCardProps {
  business: BusinessListing;
  animationDelay?: number;
}

const RANK_GRADIENTS = [
  'from-amber-500 to-yellow-400',
  'from-slate-400 to-slate-300',
  'from-amber-700 to-amber-600',
];

export default function ResultCard({ business, animationDelay = 0 }: ResultCardProps) {
  const rankGradient = RANK_GRADIENTS[business.rank - 1] ?? 'from-brand to-brand-dark';

  return (
    <div
      className="result-card group relative bg-surface-card border border-surface-border rounded-2xl p-4
                 hover:bg-surface-hover hover:border-brand/40
                 transition-all duration-300 hover:scale-[1.01] hover:shadow-lg hover:shadow-brand/10
                 animate-slide-up"
      style={{ animationDelay: `${animationDelay}ms`, animationFillMode: 'both' }}
    >
      {/* Low confidence warning */}
      {business.review_data?.low_confidence && (
        <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-amber-950/50 border border-amber-800/50 text-amber-400 text-xs">
          <AlertTriangle size={12} />
          <span>
            {business.review_data.confidence_reason ?? 'Limited review data available'}
          </span>
        </div>
      )}

      <div className="flex items-start gap-3">
        {/* Rank Badge */}
        <div
          className={cn(
            'flex-shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br flex items-center justify-center text-white font-bold text-sm shadow-md',
            rankGradient
          )}
        >
          #{business.rank}
        </div>

        {/* Main Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2 mb-1">
            <h3 className="text-slate-100 font-semibold text-base leading-tight truncate">
              {business.name}
            </h3>
            <ScoreBadge score={Math.round(business.composite_score)} size="sm" />
          </div>

          {/* Category + Source */}
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className="text-xs font-medium text-brand-light bg-brand/10 px-2 py-0.5 rounded-full capitalize">
              {business.category}
            </span>
            <span className="text-xs text-slate-500 bg-surface-DEFAULT px-2 py-0.5 rounded-full uppercase tracking-wide">
              {business.source}
            </span>
            {business.review_data?.average_rating && (
              <span className="text-xs text-amber-300 bg-amber-950/40 border border-amber-800/40 px-2 py-0.5 rounded-full inline-flex items-center gap-1">
                <Star size={10} fill="currentColor" />
                {business.review_data.average_rating.toFixed(1)}
              </span>
            )}
            {(business.review_data?.positive_percentage ?? 0) > 0 && (
              <span className="text-xs text-slate-400 bg-surface-DEFAULT px-2 py-0.5 rounded-full inline-flex items-center gap-1">
                <ThumbsUp size={10} />
                {Math.round(business.review_data.positive_percentage)}%
              </span>
            )}
          </div>

          {/* Address */}
          {business.address && (
            <div className="flex items-start gap-1.5 mb-1.5">
              <MapPin size={12} className="flex-shrink-0 mt-0.5 text-slate-500" />
              <span className="text-xs text-slate-400 leading-relaxed">{business.address}</span>
            </div>
          )}

          {/* Hours */}
          {business.opening_hours && (
            <div className="flex items-start gap-1.5 mb-1.5">
              <Clock size={12} className="flex-shrink-0 mt-0.5 text-slate-500" />
              <span className="text-xs text-slate-400 leading-relaxed">
                {business.opening_hours}
              </span>
            </div>
          )}

          {/* Phone */}
          {business.phone && (
            <div className="flex items-center gap-1.5 mb-1.5">
              <Phone size={12} className="flex-shrink-0 text-slate-500" />
              <a
                href={`tel:${business.phone}`}
                className="text-xs text-slate-400 hover:text-brand transition-colors"
              >
                {business.phone}
              </a>
            </div>
          )}

          {/* AI Summary */}
          {business.summary && (
            <p className="text-sm text-slate-400 italic mt-2 mb-3 leading-relaxed border-l-2 border-brand/30 pl-3">
              {business.summary}
            </p>
          )}

          {/* Review Themes */}
          {business.review_data?.recurring_themes?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {business.review_data.recurring_themes.slice(0, 4).map((theme) => (
                <span
                  key={theme}
                  className="text-xs text-slate-400 bg-surface-DEFAULT px-2 py-0.5 rounded-full border border-surface-border"
                >
                  {theme}
                </span>
              ))}
            </div>
          )}

          {/* Score breakdown */}
          {business.scoring_details && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 mb-3">
              {Object.entries(business.scoring_details.components).map(([key, part]) => (
                <div
                  key={key}
                  className="rounded-lg bg-surface-DEFAULT border border-surface-border px-2 py-1.5"
                >
                  <div className="flex items-center justify-between gap-1 mb-1">
                    <span className="text-[10px] text-slate-600 capitalize truncate">
                      {key.replace(/_/g, ' ')}
                    </span>
                    <Activity size={9} className="text-slate-600" />
                  </div>
                  <div className="text-xs text-slate-300 font-semibold">
                    +{part.contribution.toFixed(1)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex items-center gap-2 flex-wrap">
            {business.maps_url && (
              <a
                href={business.maps_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                           bg-brand text-white text-xs font-medium
                           hover:bg-brand-dark transition-colors"
              >
                <MapPin size={11} />
                Open in Maps
              </a>
            )}
            {business.website && (
              <a
                href={business.website}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                           bg-surface-DEFAULT border border-surface-border text-slate-400 text-xs font-medium
                           hover:border-brand/50 hover:text-brand transition-colors"
              >
                <Globe size={11} />
                Website
              </a>
            )}
            {business.phone && (
              <a
                href={`tel:${business.phone}`}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                           bg-surface-DEFAULT border border-surface-border text-slate-400 text-xs font-medium
                           hover:border-brand/50 hover:text-brand transition-colors"
              >
                <Phone size={11} />
                Call
              </a>
            )}

            {/* Review stats pill */}
            {business.review_data && business.review_data.total_reviews > 0 && (
              <span className="ml-auto text-xs text-slate-500 flex items-center gap-1">
                <ExternalLink size={10} />
                {business.review_data.total_reviews} reviews
                {business.review_data.average_rating
                  ? ` · ${business.review_data.average_rating.toFixed(1)}★`
                  : ''}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
