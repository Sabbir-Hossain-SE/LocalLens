# LocalLens — AI-Powered Local Discovery Agent

LocalLens is a conversational AI agent that takes a plain English question and returns a ranked, summarized list of local businesses — pulling live data from OpenStreetMap, DuckDuckGo, and public web sources.

**Stack:** Python 3.11 + FastAPI (backend) · Next.js 14 + Tailwind CSS (frontend)  
**Cost:** 100% free and open-source — no credit card required

---

## Architecture

```
User Query
    │
    ▼
[A] Intent Parser        → LLM extracts: category, count, location, filters
    │
    ▼
[B] Location Resolver    → IP geolocation / Nominatim geocoding → lat/lng + bbox
    │
    ▼
[C] Search Agent         → Overpass API → DuckDuckGo → Playwright (fallback chain)
    │
    ▼
[D] Review Aggregator    → Scrape ratings, HuggingFace sentiment analysis
    │
    ▼
[E] Scoring Engine       → Composite score: 40% rating + 30% reviews + 20% sentiment + 10% recency
    │
    ▼
[F] LLM Summarizer       → Grounded 2-3 sentence summary per result (no hallucination)
    │
    ▼
[G] Response Formatter   → Ranked JSON list + SSE stream to frontend
```

## Folder Structure

```
LocalLens-claude/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI entry point
│   │   ├── config.py                # pydantic-settings config
│   │   ├── models/                  # Pydantic data models
│   │   │   ├── intent.py            # ParsedIntent, SearchFilters
│   │   │   ├── location.py          # Coordinates, BoundingBox, ResolvedLocation
│   │   │   ├── business.py          # BusinessListing, ReviewData
│   │   │   └── response.py          # SearchResponse, StreamEvent
│   │   ├── modules/                 # 7 pipeline modules (A–G)
│   │   │   ├── intent_parser.py     # Module A — LLM intent extraction
│   │   │   ├── location_resolver.py # Module B — IP geo + Nominatim
│   │   │   ├── search_agent.py      # Module C — Overpass + DuckDuckGo
│   │   │   ├── review_aggregator.py # Module D — sentiment analysis
│   │   │   ├── scoring_engine.py    # Module E — composite scoring
│   │   │   ├── summarizer.py        # Module F — LLM summarization
│   │   │   └── response_formatter.py# Module G — final formatting
│   │   ├── pipeline/
│   │   │   └── orchestrator.py      # Async pipeline → SSE event generator
│   │   ├── api/routes/
│   │   │   ├── search.py            # POST /search, GET /search/stream (SSE)
│   │   │   ├── health.py            # GET /health
│   │   │   └── metrics.py           # GET /metrics
│   │   └── utils/
│   │       ├── cache.py             # diskcache wrapper
│   │       ├── logger.py            # structlog structured logging
│   │       └── rate_limiter.py      # per-domain rate limiting
│   ├── config/
│   │   └── scoring_weights.yaml     # Externalized scoring weights
│   ├── tests/                       # pytest test suite
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/                     # Next.js App Router pages
│   │   ├── components/
│   │   │   ├── layout/              # Sidebar, MainLayout
│   │   │   ├── chat/                # ChatArea, SearchInput, PipelineProgress
│   │   │   ├── results/             # ResultCard, ResultsList, ScoreBadge
│   │   │   └── map/                 # MapPanel (Leaflet, dark tiles)
│   │   ├── lib/                     # types.ts, api.ts, utils.ts
│   │   ├── hooks/                   # useSearch.ts (SSE consumer)
│   │   └── store/                   # Zustand chat session store
│   └── package.json
├── docker-compose.yml
└── README.md
```

## Quick Start

### Option A — Local Development (Recommended)

**Prerequisites:** Python 3.11+, Node.js 20+

#### 1. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — set LLM_PROVIDER and GROQ_API_KEY if using Groq

# Run the API server
uvicorn app.main:app --reload --port 8000
```

Backend will be available at `http://localhost:8000`  
Swagger docs: `http://localhost:8000/docs`

#### 2. LLM Setup (choose one)

**Option A: Ollama (fully local, no API key)**
```bash
# Install from https://ollama.ai
ollama pull llama3      # or mistral, llama3:8b, etc.
ollama serve
# Set in .env: LLM_PROVIDER=ollama, LLM_MODEL=llama3
```

**Option B: Groq (fast, free tier, no credit card)**
```bash
# Get free API key at https://console.groq.com
# Set in .env: LLM_PROVIDER=groq, GROQ_API_KEY=your_key_here, LLM_MODEL=llama3-8b-8192
```

> **Note:** Even without LLM configured, the system works — it falls back to regex-based intent parsing and template-based summaries.

#### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Configure environment
cp .env.local.example .env.local

# Start dev server
npm run dev
```

Frontend will be available at `http://localhost:3000`

### Option B — Docker Compose

```bash
# Set your Groq API key (optional)
export GROQ_API_KEY=your_key_here

docker-compose up --build
```

Services:
- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- Ollama: `http://localhost:11434`

---

## API Endpoints

### `POST /search`
Synchronous search — waits for full pipeline to complete.

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "best 3 sushi restaurants near me", "user_ip": "8.8.8.8"}'
```

### `GET /search/stream?query=...`
SSE streaming — yields events as each pipeline step completes.

```bash
curl -N "http://localhost:8000/search/stream?query=coffee+shops+in+Austin"
```

Stream events (in order):
| Event | Data |
|-------|------|
| `intent_parsed` | ParsedIntent JSON |
| `location_resolved` | ResolvedLocation JSON |
| `search_complete` | raw listings count |
| `reviews_aggregated` | enriched listings |
| `scoring_complete` | ranked listings |
| `summary_ready` | final with summaries |
| `done` | complete SearchResponse |

### `GET /health`
```json
{"status": "healthy", "version": "1.0.0", "llm_provider": "groq"}
```

### `GET /metrics`
```json
{"total_queries": 42, "cache_hit_rate": 0.38, "avg_latency_ms": 2100, "errors": 1}
```

---

## Sample Queries

| Query | Location Type | Category |
|-------|--------------|----------|
| `Find me the best 3 sushi restaurants near me` | IP geolocation | Restaurant |
| `Best 5 meditation centers near me` | IP geolocation | Wellness |
| `5 tax filing companies in Irvine CA` | Named city | Financial |
| `Top 4 grocery stores near zip code 10001` | ZIP code | Retail |
| `Best co-working spaces open weekends in Austin` | Named city + filter | Workspace |
| `3 highly rated dentists within 10km of me` | Geo + radius | Healthcare |
| `Affordable yoga studios near downtown Seattle` | Named area + filter | Fitness |

---

## Configuration

### Scoring Weights (`backend/config/scoring_weights.yaml`)

```yaml
default:
  star_rating: 0.40     # Weight for average star rating
  review_count: 0.30    # Weight for volume of reviews  
  sentiment_score: 0.20 # Weight for HuggingFace sentiment
  recency_signal: 0.10  # Weight for review recency

category_overrides:
  restaurant:
    star_rating: 0.45
    review_count: 0.25
```

All weights are externalized — no code changes needed to tune scoring.

### Environment Variables (`backend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | `ollama` or `groq` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `LLM_MODEL` | `llama3` | Model name |
| `GROQ_API_KEY` | *(empty)* | Groq API key (free at console.groq.com) |
| `CACHE_TTL_SECONDS` | `3600` | Query cache TTL (1 hour) |
| `CACHE_DIR` | `.cache` | Disk cache directory |
| `DEFAULT_LOCATION_LAT` | `40.7128` | Fallback latitude (New York) |
| `DEFAULT_LOCATION_LNG` | `-74.0060` | Fallback longitude |

---

## Running Tests

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v --tb=short
```

Test coverage targets: 70%+ per module.

---

## Technology Stack

| Category | Technology | Purpose |
|----------|-----------|---------|
| Backend Language | Python 3.11+ | All pipeline modules |
| API Framework | FastAPI | REST + SSE endpoints |
| LLM Framework | LangChain | Agent orchestration |
| LLM — Local | Ollama + Llama 3 | Zero-cost local inference |
| LLM — Hosted | Groq API (free tier) | Fast hosted inference |
| Places Search | Overpass API (OSM) | Primary business lookup |
| Geocoding | Nominatim (OSM) | City/ZIP → coordinates |
| IP Geolocation | ip-api.com | "Near me" resolution |
| Web Search | DuckDuckGo | Fallback business search |
| Web Scraping | Playwright + BS4 | Review scraping |
| NLP / Sentiment | HuggingFace Transformers | Review sentiment scoring |
| Caching | diskcache | Local query result caching |
| Frontend | Next.js 14 | React-based UI |
| Styling | Tailwind CSS | Dark theme, responsive |
| Map | Leaflet + react-leaflet | Interactive location map |
| State | Zustand | Chat session management |

---

## Delivery Milestones (from spec)

- [x] **Week 1-2 (Foundation):** Module A — Intent Parser with 30+ test query coverage
- [x] **Week 3 (Data Layer):** Module B + C — Location resolved, OSM search returning raw results
- [x] **Week 4 (Intelligence):** Module D + E — Reviews scraped, sentiment run, rankings computed
- [x] **Week 5 (LLM Layer):** Module F — Grounded LLM summaries per result
- [x] **Week 6 (Integration):** Module G — Full FastAPI service running end-to-end
- [x] **Week 7-8 (Polish):** SSE streaming, caching, frontend UI, Docker setup
