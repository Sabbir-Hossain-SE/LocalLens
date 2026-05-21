'use client';

import { useEffect, useRef } from 'react';
import { MapPin, ExternalLink, Navigation, Star, Workflow, Database } from 'lucide-react';
import type { BusinessListing, SearchResponse } from '@/lib/types';
import { formatElapsed, getScoreColor } from '@/lib/utils';

interface MapPanelProps {
  response?: SearchResponse;
  results: BusinessListing[];
  location: string;
}

// Minimal Leaflet type shims (loaded dynamically to avoid SSR issues)
type LeafletMap = {
  remove: () => void;
  setView: (latlng: [number, number], zoom: number) => LeafletMap;
  fitBounds: (bounds: unknown) => void;
};

interface LeafletMarker {
  addTo: (map: LeafletMap) => LeafletMarker;
  bindPopup: (html: string) => LeafletMarker;
  openPopup: () => LeafletMarker;
}

declare global {
  interface Window {
    L: {
      map: (el: HTMLElement) => LeafletMap;
      tileLayer: (url: string, opts: Record<string, unknown>) => { addTo: (map: LeafletMap) => void };
      marker: (latlng: [number, number], opts?: Record<string, unknown>) => LeafletMarker;
      divIcon: (opts: Record<string, unknown>) => unknown;
      latLngBounds: (coords: [number, number][]) => unknown;
    };
  }
}

export default function MapPanel({ response, results, location }: MapPanelProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<LeafletMap | null>(null);

  const geocodedResults = results.filter((r) => r.lat !== null && r.lng !== null);
  const topResult = results[0];
  const sourceCounts = results.reduce<Record<string, number>>((acc, item) => {
    acc[item.source] = (acc[item.source] ?? 0) + 1;
    return acc;
  }, {});
  const pipelineSteps = response?.pipeline_steps ?? [];

  // Build Google Maps URL for route (all results)
  const googleMapsUrl = geocodedResults.length > 0
    ? `https://www.google.com/maps/search/${encodeURIComponent(
        geocodedResults[0]?.name ?? location
      )}`
    : `https://www.google.com/maps/search/${encodeURIComponent(location)}`;

  useEffect(() => {
    if (!mapContainerRef.current) return;
    if (typeof window === 'undefined') return;

    // Load Leaflet CSS dynamically
    if (!document.getElementById('leaflet-css')) {
      const link = document.createElement('link');
      link.id = 'leaflet-css';
      link.rel = 'stylesheet';
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      document.head.appendChild(link);
    }

    // Load Leaflet JS dynamically
    const loadLeaflet = async () => {
      if (!window.L) {
        await new Promise<void>((resolve, reject) => {
          const script = document.createElement('script');
          script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
          script.onload = () => resolve();
          script.onerror = reject;
          document.head.appendChild(script);
        });
      }

      if (!mapContainerRef.current) return;

      // Remove existing map instance
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }

      const L = window.L;
      const map = L.map(mapContainerRef.current);

      // Dark CartoDB tile layer
      L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
        {
          attribution: '&copy; OpenStreetMap &copy; CARTO',
          subdomains: 'abcd',
          maxZoom: 19,
        }
      ).addTo(map);

      mapInstanceRef.current = map;

      if (geocodedResults.length === 0) {
        map.setView([40.7128, -74.006], 11);
        return;
      }

      const bounds: [number, number][] = [];

      geocodedResults.forEach((biz) => {
        const lat = biz.lat!;
        const lng = biz.lng!;
        bounds.push([lat, lng]);

        const color = getScoreColor(Math.round(biz.composite_score));

        const icon = L.divIcon({
          className: '',
          html: `<div style="
            width: 28px; height: 28px; border-radius: 50%;
            background: ${color}; color: white;
            display: flex; align-items: center; justify-content: center;
            font-weight: 700; font-size: 12px;
            border: 2px solid rgba(255,255,255,0.3);
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
          ">${biz.rank}</div>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        });

        const popupHtml = `
          <div style="font-family: Inter, sans-serif; min-width: 180px;">
            <div style="font-weight: 700; color: #f1f5f9; margin-bottom: 4px;">${biz.name}</div>
            ${biz.address ? `<div style="color: #94a3b8; font-size: 12px; margin-bottom: 4px;">${biz.address}</div>` : ''}
            <div style="color: ${color}; font-size: 13px; font-weight: 600;">Score: ${Math.round(biz.composite_score)}/100</div>
            ${biz.maps_url ? `<a href="${biz.maps_url}" target="_blank" style="color: #10b981; font-size: 12px; text-decoration: none; display: block; margin-top: 6px;">Open in Maps →</a>` : ''}
          </div>
        `;

        L.marker([lat, lng] as [number, number], { icon })
          .addTo(map)
          .bindPopup(popupHtml);
      });

      if (bounds.length === 1) {
        map.setView(bounds[0], 14);
      } else if (bounds.length > 1) {
        map.fitBounds(L.latLngBounds(bounds));
      }
    };

    loadLeaflet().catch(console.error);

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, [results, geocodedResults, location]);

  return (
    <div className="flex flex-col h-full bg-surface-DEFAULT">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-4 border-b border-surface-border">
        <div className="flex items-center gap-2 mb-1">
          <MapPin size={16} className="text-brand" />
          <h2 className="text-slate-200 font-semibold text-sm">Map & Locations</h2>
        </div>
        {location && (
          <p className="text-slate-500 text-xs flex items-center gap-1">
            <Navigation size={10} />
            Your area: {location}
          </p>
        )}
        <a
          href={googleMapsUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-1.5 text-xs text-brand hover:text-brand-light transition-colors"
        >
          <ExternalLink size={11} />
          Open in Google Maps
        </a>
      </div>

      {topResult && (
        <div className="flex-shrink-0 px-4 py-3 border-b border-surface-border bg-surface-card/45">
          <div className="flex items-start justify-between gap-3 mb-2">
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wide text-slate-600 font-semibold">
                Top score
              </p>
              <h3 className="text-sm font-semibold text-slate-200 truncate">
                {topResult.name}
              </h3>
            </div>
            <div className="text-right">
              <div className="text-xl font-bold text-brand">
                {Math.round(topResult.composite_score)}
              </div>
              <div className="text-[10px] text-slate-600">/100</div>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Star size={12} className="text-amber-400" fill="currentColor" />
            <span>
              {topResult.review_data.average_rating
                ? `${topResult.review_data.average_rating.toFixed(1)} rating`
                : 'No rating'}
            </span>
            <span>·</span>
            <span>{topResult.review_data.total_reviews} reviews</span>
          </div>
        </div>
      )}

      {response && (
        <div className="flex-shrink-0 px-4 py-3 border-b border-surface-border">
          <div className="grid grid-cols-3 gap-2 mb-3">
            <div className="rounded-lg bg-surface-card/50 border border-surface-border px-2 py-2">
              <div className="text-sm font-semibold text-slate-200">{response.total_results}</div>
              <div className="text-[10px] text-slate-600">ranked</div>
            </div>
            <div className="rounded-lg bg-surface-card/50 border border-surface-border px-2 py-2">
              <div className="text-sm font-semibold text-slate-200">
                {formatElapsed(response.elapsed_ms)}
              </div>
              <div className="text-[10px] text-slate-600">runtime</div>
            </div>
            <div className="rounded-lg bg-surface-card/50 border border-surface-border px-2 py-2">
              <div className="text-sm font-semibold text-slate-200">
                {Object.keys(sourceCounts).length}
              </div>
              <div className="text-[10px] text-slate-600">sources</div>
            </div>
          </div>

          <div className="flex items-center gap-1.5 mb-2 text-[11px] text-slate-500">
            <Database size={12} className="text-brand" />
            Source coverage
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(sourceCounts).map(([source, count]) => (
              <span
                key={source}
                className="px-2 py-1 rounded-md bg-surface-card border border-surface-border text-[11px] text-slate-400 uppercase"
              >
                {source} {count}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Map container */}
      <div className="flex-shrink-0 h-56 relative">
        <div ref={mapContainerRef} className="absolute inset-0" />
        {geocodedResults.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface-card/80 z-10">
            <div className="text-center">
              <MapPin size={24} className="text-slate-600 mx-auto mb-2" />
              <p className="text-slate-500 text-xs">No coordinates available</p>
            </div>
          </div>
        )}
      </div>

      {/* Results compact list */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        <div className="px-3 py-2 border-b border-surface-border">
          <span className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
            {results.length} Location{results.length !== 1 ? 's' : ''}
          </span>
        </div>
        <div className="divide-y divide-surface-border">
          {results.map((biz) => {
            const color = getScoreColor(Math.round(biz.composite_score));
            return (
              <div key={biz.id} className="flex items-center gap-3 px-3 py-2.5 hover:bg-surface-card/50 transition-colors">
                {/* Rank dot */}
                <div
                  className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-white text-xs font-bold"
                  style={{ backgroundColor: color }}
                >
                  {biz.rank}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-slate-300 text-xs font-medium truncate">{biz.name}</p>
                  {biz.address && (
                    <p className="text-slate-600 text-xs truncate">{biz.address}</p>
                  )}
                </div>

                {/* Score + link */}
                <div className="flex-shrink-0 flex items-center gap-2">
                  <span className="text-xs font-semibold" style={{ color }}>
                    {Math.round(biz.composite_score)}
                  </span>
                  {biz.maps_url && (
                    <a
                      href={biz.maps_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-slate-600 hover:text-brand transition-colors"
                      aria-label={`Open ${biz.name} in maps`}
                    >
                      <ExternalLink size={11} />
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {topResult?.scoring_details && (
        <div className="flex-shrink-0 border-t border-surface-border bg-surface-DEFAULT px-4 py-3 max-h-[45vh] overflow-y-auto scrollbar-thin">
          {pipelineSteps.length > 0 && (
            <div className="mb-4">
              <div className="flex items-center gap-1.5 mb-2">
                <Workflow size={12} className="text-brand" />
                <h3 className="text-xs font-semibold text-slate-300">Pipeline detail</h3>
              </div>
              <div className="space-y-1.5">
                {pipelineSteps.slice(0, 7).map((step) => (
                  <div
                    key={String(step.stage)}
                    className="flex items-center justify-between gap-2 text-[11px]"
                  >
                    <span className="text-slate-500 truncate">
                      {String(step.stage).replace(/_/g, ' ')}
                    </span>
                    <span className="text-slate-400">
                      {typeof step.elapsed_ms === 'number' ? formatElapsed(step.elapsed_ms) : step.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold text-slate-300">Score details</h3>
            <span className="text-xs text-brand font-semibold">
              {Math.round(topResult.scoring_details.final_score)}/100
            </span>
          </div>
          <div className="space-y-2">
            {Object.entries(topResult.scoring_details.components).map(([key, part]) => {
              const label = key.replace(/_/g, ' ');
              return (
                <div key={key}>
                  <div className="flex items-center justify-between text-[11px] mb-1">
                    <span className="text-slate-500 capitalize">{label}</span>
                    <span className="text-slate-400">
                      +{part.contribution.toFixed(1)}
                    </span>
                  </div>
                  <div className="h-1.5 bg-surface-card rounded-full overflow-hidden">
                    <div
                      className="h-full bg-brand"
                      style={{ width: `${Math.max(3, Math.min(100, part.normalised * 100))}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-[11px] text-slate-600 mt-2 leading-relaxed">
            {topResult.scoring_details.explanation}
          </p>
        </div>
      )}
    </div>
  );
}
