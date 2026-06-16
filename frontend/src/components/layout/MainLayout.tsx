'use client';

import dynamic from 'next/dynamic';
import { useChatStore } from '@/store/chatStore';
import Sidebar from './Sidebar';
import SystemStatusPanel from './SystemStatusPanel';
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

  const latestResponse = latestResultMessage?.response;
  const mapResults = latestResponse?.results ?? [];
  const mapLocation = latestResponse?.location ?? '';
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
          <MapPanel response={latestResponse} results={mapResults} location={mapLocation} />
        ) : (
          <SystemStatusPanel />
        )}
      </aside>
    </div>
  );
}
