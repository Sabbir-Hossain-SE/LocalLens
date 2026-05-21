export interface SearchFilters {
  open_now: boolean;
  min_rating: number | null;
  price_level: string | null;
  max_distance_km: number | null;
}

export interface ParsedIntent {
  category: string;
  count: number;
  location: string;
  radius_km: number;
  sort_by: string;
  filters: SearchFilters;
  raw_query: string;
  confidence: number;
}

export interface ReviewData {
  total_reviews: number;
  average_rating: number | null;
  positive_percentage: number;
  negative_percentage: number;
  recurring_themes: string[];
  recency_score: number;
  sample_reviews: string[];
  low_confidence: boolean;
  confidence_reason: string | null;
}

export interface BusinessListing {
  id: string;
  name: string;
  address: string | null;
  lat: number | null;
  lng: number | null;
  category: string;
  phone: string | null;
  website: string | null;
  opening_hours: string | null;
  source: string;
  review_data: ReviewData;
  composite_score: number;
  rank: number;
  summary: string | null;
  maps_url: string | null;
}

export interface SearchResponse {
  query: string;
  location: string;
  total_results: number;
  results: BusinessListing[];
  elapsed_ms: number;
  pipeline_steps: PipelineStep[];
}

export interface PipelineStep {
  step: string;
  status: 'pending' | 'running' | 'done' | 'error';
  detail?: string;
}

export type StreamEventType =
  | 'intent_parsed'
  | 'location_resolved'
  | 'search_complete'
  | 'reviews_aggregated'
  | 'scoring_complete'
  | 'summary_ready'
  | 'clarification_needed'
  | 'done'
  | 'error';

export interface ClarificationPayload {
  question: string;
  options: string[];
  current_category?: string;
  current_location?: string;
}

export interface StreamEvent {
  event: StreamEventType;
  data: Record<string, unknown>;
  step: number;
  total_steps: number;
}

export type MessageType = 'user' | 'assistant' | 'error';

export interface ChatMessage {
  id: string;
  type: MessageType;
  query?: string;
  response?: SearchResponse;
  pipelineSteps?: PipelineStep[];
  isStreaming?: boolean;
  timestamp: Date;
  errorMessage?: string;
  clarification?: ClarificationPayload;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: Date;
}
