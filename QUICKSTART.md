# ResearchMindAI - Quick Start Guide

## Prerequisites Check

Before starting, ensure you have:
- ✅ Docker Desktop installed and running
- ✅ Python 3.11+ installed
- ✅ Git installed
- ✅ OpenAI API account (free $5 credit for new accounts)

## Step-by-Step Setup

### 1. Start Docker Services (PostgreSQL + Redis)

Open **Windows PowerShell** or **Command Prompt** and run:

```powershell
cd C:\Users\ranga\OneDrive\Desktop\ResearchAI\researchmind-ai\docker

# Start services
docker-compose -f docker-compose.dev.yml up -d

# Verify they're running (should see 2 containers)
docker ps
```

**Expected output:**
```
CONTAINER ID   IMAGE                    PORTS                    STATUS
xxxxx          pgvector/pgvector:pg15   0.0.0.0:5432->5432/tcp   Up
xxxxx          redis:7-alpine           0.0.0.0:6379->6379/tcp   Up
```

✅ **If you see both containers running, proceed to Step 2**

❌ **If containers fail to start:**
- Ensure Docker Desktop is running
- Check if ports 5432 or 6379 are already in use
- Run: `docker-compose -f docker-compose.dev.yml logs` to see errors

---

### 2. Setup Python Environment

Open a **new PowerShell window**:

```powershell
cd C:\Users\ranga\OneDrive\Desktop\ResearchAI\researchmind-ai\backend

# Create virtual environment
python -m venv venv

# Activate it
.\venv\Scripts\activate

# Your prompt should now show (venv)
```

---

### 3. Install Dependencies

With the virtual environment activated:

```powershell
# Install all packages (takes 2-3 minutes)
pip install -r requirements.txt

# Verify installation
pip list | Select-String "fastapi|sqlalchemy|openai"
```

**Expected:** Should see fastapi, sqlalchemy, openai, and other packages listed.

---

### 4. Configure API Keys

Edit the `.env` file in the `backend` directory:

**File:** `C:\Users\ranga\OneDrive\Desktop\ResearchAI\researchmind-ai\backend\.env`

**Update these lines:**

```ini
# OpenAI - REQUIRED
OPENAI_API_KEY=sk-your-actual-api-key-here

# PubMed - OPTIONAL (improves rate limits)
PUBMED_EMAIL=ranganath.sk@hotmail.com

# OpenAlex - OPTIONAL (improves rate limits)
OPENALEX_EMAIL=ranganath.sk@hotmail.com
```

**To get OpenAI API key:**
1. Go to https://platform.openai.com/api-keys
2. Sign in or create account (free $5 credit)
3. Click "Create new secret key"
4. Copy the key (starts with `sk-`)
5. Paste it in the `.env` file

**PubMed API key (optional):**
- Sign up at https://www.ncbi.nlm.nih.gov/account/
- Navigate to Settings → API Key Management

---

### 5. Verify Setup

Run the verification script:

```powershell
# Make sure you're in backend directory with venv activated
python setup.py
```

**Expected output:**
```
Checking ResearchMindAI Backend Setup...
==================================================
✓ Python version: 3.11.x
✓ .env file found

Checking dependencies:
  ✓ fastapi
  ✓ sqlalchemy
  ✓ redis
  ✓ celery
  ✓ openai
  ✓ chromadb
  ✓ langchain

==================================================
Setup check complete!
```

---

### 6. Start the Backend API

```powershell
# Still in backend directory with venv activated
python -m app.main
```

**Expected output:**
```
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Starting ResearchMindAI v1.0.0
INFO:     Required directories created/verified
INFO:     Database tables created/verified
INFO:     Application startup complete
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

✅ **Backend is now running!**

---

### 7. Test the API

Open your web browser and visit these URLs:

**1. Root Endpoint:**
http://localhost:8000

Should show:
```json
{
  "message": "Welcome to ResearchMindAI API",
  "version": "1.0.0",
  "docs": "/api/docs",
  "health": "/health"
}
```

**2. Health Check:**
http://localhost:8000/health

Should show:
```json
{
  "status": "healthy",
  "app_name": "ResearchMindAI",
  "version": "1.0.0",
  "database": "healthy"
}
```

**3. Interactive API Documentation:**
http://localhost:8000/api/docs

Should show Swagger UI with interactive API documentation.

---

## ✅ Success! You're Ready to Code

If all tests pass, your development environment is fully set up.

### What's Working:
- ✅ PostgreSQL database with pgvector
- ✅ Redis cache
- ✅ FastAPI backend with health check
- ✅ Database connection verified
- ✅ All dependencies installed
- ✅ API documentation auto-generated

### Next Steps:

**Option A: Start Building Authentication**
```powershell
git checkout feature/authentication
# Start implementing user models, JWT, etc.
```

**Option B: Explore the API**
- Visit http://localhost:8000/api/docs
- Try the health check endpoint
- Look at the code structure

**Option C: Read the Plan**
- Review `BRANCHES.md` for branching strategy
- Check the implementation plan at `.claude/plans/warm-wiggling-kurzweil.md`

---

## Troubleshooting

### Docker containers won't start
```powershell
# Stop all containers
docker-compose -f docker-compose.dev.yml down

# Remove volumes (WARNING: deletes data)
docker-compose -f docker-compose.dev.yml down -v

# Start again
docker-compose -f docker-compose.dev.yml up -d
```

### Port already in use (5432 or 6379)
```powershell
# Find what's using the port
netstat -ano | findstr :5432
netstat -ano | findstr :6379

# Kill the process or change ports in docker-compose.dev.yml
```

### Virtual environment activation fails
```powershell
# If using PowerShell with restricted execution policy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Then try activating again
.\venv\Scripts\activate
```

### Module not found errors
```powershell
# Ensure venv is activated (you should see (venv) in prompt)
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### Database connection fails
```powershell
# Check if PostgreSQL container is running
docker ps | findstr postgres

# Check logs
docker logs researchmind_postgres

# Restart containers
docker restart researchmind_postgres researchmind_redis
```

---

## Stopping the Environment

When you're done working:

```powershell
# Stop the backend (Ctrl+C in the terminal running it)

# Stop Docker containers (keeps data)
cd docker
docker-compose -f docker-compose.dev.yml stop

# Or remove containers completely (deletes data)
docker-compose -f docker-compose.dev.yml down
```

---

## Development Workflow

```powershell
# Starting a work session
1. cd C:\Users\ranga\OneDrive\Desktop\ResearchAI\researchmind-ai
2. git checkout develop
3. git pull origin develop
4. cd docker && docker-compose -f docker-compose.dev.yml up -d
5. cd ../backend && .\venv\Scripts\activate
6. git checkout feature/authentication (or other feature)
7. python -m app.main

# Ending a work session
1. Ctrl+C (stop backend)
2. cd ../docker && docker-compose -f docker-compose.dev.yml stop
3. deactivate (exit venv)
```

---

**Ready to start coding! 🚀**
