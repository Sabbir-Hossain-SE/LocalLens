'use client';

import dynamic from 'next/dynamic';
import { useChatStore } from '@/store/chatStore';
import Sidebar from './Sidebar';
import ChatArea from '@/components/chat/ChatArea';

// Load MapPanel dynamically to avoid SSR issues with Leaflet
const MapPanel = dynamic(() => import('@/components/map/MapPanel'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full bg-surface-DEFAULT">
      <div className="text-slate-600 text-sm">Loading map...</div>
    </div>
  ),
});

export default function MainLayout() {
  const { getCurrentSession } = useChatStore();
  const session = getCurrentSession();

  // Find the latest assistant message with results to drive the map
  const latestResultMessage = session?.messages
    .slice()
    .reverse()
    .find((m) => m.type === 'assistant' && m.response && !m.isStreaming);

  const mapResults = latestResultMessage?.response?.results ?? [];
  const mapLocation = latestResultMessage?.response?.location ?? '';
  const showMap = mapResults.length > 0;

  return (
    <div className="flex h-screen bg-surface-deep overflow-hidden">
      {/* Left sidebar */}
      <div className="flex-shrink-0 w-64">
        <Sidebar />
      </div>

      {/* Main chat area */}
      <main
        className="flex-1 min-w-0 flex flex-col border-x border-surface-border bg-surface-deep"
      >
        <ChatArea />
      </main>

      {/* Right map panel */}
      <aside className="flex flex-col flex-shrink-0 w-80 border-l border-surface-border overflow-hidden">
        {showMap ? (
          <MapPanel results={mapResults} location={mapLocation} />
        ) : (
          <div className="flex flex-col items-center justify-center h-full bg-surface-DEFAULT text-center px-6">
            <div className="w-16 h-16 rounded-2xl bg-surface-card border border-surface-border flex items-center justify-center mb-4">
              <svg
                width="28"
                height="28"
                viewBox="0 0 28 28"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <circle cx="14" cy="14" r="7" stroke="#334155" strokeWidth="2" />
                <circle cx="14" cy="14" r="2.5" fill="#334155" />
                <line x1="14" y1="4" x2="14" y2="8" stroke="#334155" strokeWidth="1.5" strokeLinecap="round" />
                <line x1="14" y1="20" x2="14" y2="24" stroke="#334155" strokeWidth="1.5" strokeLinecap="round" />
                <line x1="4" y1="14" x2="8" y2="14" stroke="#334155" strokeWidth="1.5" strokeLinecap="round" />
                <line x1="20" y1="14" x2="24" y2="14" stroke="#334155" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </div>
            <h3 className="text-slate-500 font-semibold text-sm mb-1">Map & Locations</h3>
            <p className="text-slate-700 text-xs leading-relaxed">
              Search for local businesses to see them plotted on the map.
            </p>
          </div>
        )}
      </aside>
    </div>
  );
}
