# ResearchMindAI

AI-powered research collaboration platform for automated literature reviews.

## POC (branch `poc`) — quick start

Type a research topic and get, in about two minutes: relevant papers from
OpenAlex, Semantic Scholar, PubMed and arXiv; the main themes; research gaps;
a chat that answers with citations; and a literature review (DOCX/PDF, APA or IEEE).
You can also upload your own PDFs, save and reopen sessions, and share them as
viewer or contributor.

```bash
cp backend/.env.example backend/.env   # add OPENAI_API_KEY (+ optional keys)
docker compose up -d --build           # UI http://localhost:8501 · API http://localhost:8000/api/docs
docker compose --profile share up -d   # + public test link (see DEPLOY.md)
```

See **[DEPLOY.md](DEPLOY.md)** for sharing a test link, AWS deployment and local dev.

| Area | Where |
|---|---|
| Paper discovery (query planning, routing, dedupe, ranking) | `backend/app/services/discovery_service.py` |
| Sources (free; keys optional) | `openalex_service.py`, `semantic_scholar_service.py`, `pubmed_service.py`, `arxiv_service.py` |
| Retries, rate pacing, API cache | `backend/app/services/http_utils.py` |
| Themes (k-means + LLM) and gaps | `backend/app/services/analysis_service.py` |
| Chat with validated citations | `backend/app/services/chat_service.py` |
| PDF/DOCX upload | `backend/app/services/upload_service.py` |
| Literature review export | `backend/app/services/export_service.py` |
| Sharing and permissions | `backend/app/services/access.py` |
| UI | `backend/ui/app.py` |
| API | `backend/app/api/v1/research.py` (+ existing auth/sessions/papers/knowledge-map) |
| Tests (offline, no keys) | `backend/tests/` → `cd backend && pytest` |

POC design notes: vectors are stored in Postgres (`paper_chunks`) and searched in
numpy, replacing ChromaDB, so the only stateful service is Postgres. Claude is
used for analysis when `ANTHROPIC_API_KEY` is set, otherwise OpenAI. Work runs
in the request (no Celery yet).

## Features (V1)

- 🔬 **Session Management** - Create research sessions with specific topics
- 📚 **Paper Ingestion** - Auto-fetch papers from Semantic Scholar, PubMed, OpenAlex
- 🗺️ **Knowledge Maps** - AI-generated synthesis of themes, findings, and authors
- 💬 **RAG Chat** - Conversational Q&A with citations
- 🔍 **Gap Analysis** - AI-identified research opportunities
- 👥 **Collaboration** - Team sharing with permissions
- 📄 **Export** - PDF export of sessions

## Tech Stack

**Backend:**
- FastAPI (Python 3.11+)
- PostgreSQL 15+ (also stores embeddings in the POC)
- Redis 7+ and Celery (planned for background jobs)

**Frontend:**
- POC: Streamlit (`backend/ui/app.py`)
- Planned: React 18+ with TypeScript
- Vite
- shadcn/ui + Tailwind CSS
- TanStack Query + Zustand

**AI:**
- Claude (when ANTHROPIC_API_KEY is set) or OpenAI gpt-4o-mini for analysis and chat
- OpenAI text-embedding-3-small for embeddings

## Prerequisites

- Docker Desktop
- Python 3.11+
- Node.js 18+
- Git

## Quick Start

### 1. Clone and Setup

```bash
cd researchmind-ai
```

### 2. Start Database Services

```bash
cd docker
docker-compose -f docker-compose.dev.yml up -d
```

Verify services are running:
```bash
docker ps
```

You should see `researchmind_postgres` and `researchmind_redis` running.

### 3. Setup Backend

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env

# Edit .env and add your OpenAI API key
# OPENAI_API_KEY=your-key-here
```

### 4. Run Backend

```bash
# Make sure you're in the backend directory with venv activated
python -m app.main

# Or using uvicorn directly:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- API: http://localhost:8000
- Docs: http://localhost:8000/api/docs
- Health Check: http://localhost:8000/health

### 5. Setup Frontend (Coming Soon)

```bash
cd frontend
npm install
npm run dev
```

## API Keys

### Required:
- **OpenAI API Key**: Get from https://platform.openai.com/api-keys
  - New accounts get $5 free credit

### Optional but Recommended:
- **PubMed API Key**: Get from https://www.ncbi.nlm.nih.gov/account/
  - Increases rate limit from 3 to 10 requests/second
- **OpenAlex Email**: Add your email for polite pool access
  - Increases rate limit to 10 requests/second

## Project Structure

```
researchmind-ai/
├── backend/           # FastAPI backend
│   ├── app/
│   │   ├── api/v1/   # API endpoints
│   │   ├── models/   # Database models
│   │   ├── schemas/  # Pydantic schemas
│   │   ├── services/ # Business logic
│   │   ├── workers/  # Celery tasks
│   │   ├── integrations/ # External APIs
│   │   ├── utils/    # Utilities
│   │   └── core/     # Core functionality
│   └── tests/
├── frontend/          # React frontend
├── docker/            # Docker config
└── data/              # Local data (git-ignored)
```

## Development

### Running Tests

```bash
cd backend
pytest
```

### Database Migrations

```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
```

### Code Formatting

```bash
black app/
flake8 app/
```

## Cost Estimate

**MVP Development:**
- Infrastructure: **$0/month** (localhost)
- OpenAI API: **$5-10/month**
- Academic APIs: **$0/month** (free with rate limits)

**Per Session (50 papers):**
- Embeddings: $0.0003
- Knowledge Map: $0.0025
- Gap Analysis: $0.0025
- Chat (10 Q&A): $0.01
- **Total: ~$0.02/session**

## Timeline

- **Week 1-2**: Foundation (Auth, Sessions)
- **Week 3-4**: Session Management
- **Week 5-6**: Paper Ingestion APIs
- **Week 7**: Embedding Pipeline
- **Week 8-9**: Knowledge Map Generation
- **Week 10**: RAG Chat
- **Week 11**: Gap Analysis
- **Week 12**: Collaboration & Sharing
- **Week 13-14**: Export & Polish

**Total: 12-14 weeks to V1**

## License

MIT

