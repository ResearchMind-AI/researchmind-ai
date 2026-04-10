# ResearchMindAI

AI-powered research collaboration platform for automated literature reviews.

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
- PostgreSQL 15+ with pgvector
- Redis 7+
- Celery for background tasks
- Chroma for vector storage

**Frontend:**
- React 18+ with TypeScript
- Vite
- shadcn/ui + Tailwind CSS
- TanStack Query + Zustand

**AI:**
- OpenAI GPT-3.5-turbo
- OpenAI text-embedding-3-small
- LangChain for RAG

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

