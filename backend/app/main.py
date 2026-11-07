"""
ResearchMindAI FastAPI Application
Main entry point for the backend API
"""
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.config import settings, ensure_directories
from app.core.database import get_db, init_db
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered research collaboration platform for literature reviews",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    if settings.SECRET_KEY in ("change-me", "dev-secret-key-change-in-production") or len(settings.SECRET_KEY) < 16:
        logger.warning("SECRET_KEY is a default/short value. Set a long random SECRET_KEY before deploying.")

    # Ensure required directories exist
    ensure_directories()
    logger.info("Required directories created/verified")

    # Create database tables
    try:
        init_db()
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")

    logger.info("Application startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown"""
    logger.info(f"Shutting down {settings.APP_NAME}")


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint
    Returns application status and database connectivity
    """
    try:
        # Test database connection
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "unhealthy"

    from app.services.discovery_service import source_status
    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "database": db_status,
        "llm_provider": "offline" if settings.OFFLINE_DEMO else settings.llm_provider,
        "sources": {s["name"]: s["mode"] for s in source_status()},
    }


# API v1 routers
from app.api.v1 import auth, teams, sessions, papers, knowledge_map, research, web_auth

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(teams.router, prefix="/api/v1/teams", tags=["Teams"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["Sessions"])
app.include_router(papers.router, prefix="/api/v1/papers", tags=["Papers"])
app.include_router(knowledge_map.router, prefix="/api/v1/knowledge-map", tags=["Knowledge Map"])
app.include_router(research.router, prefix="/api/v1/research", tags=["Research (POC)"])
app.include_router(web_auth.router, prefix="/api/v1/web", tags=["Web app auth"])



# ── Web app (React build) ─────────────────────────────────────────────────────
# The Docker image copies the built frontend to /app/web; locally we fall back to
# ../frontend/dist. Registered after the API routes so /api/* always wins.
import os
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_here = Path(__file__).resolve().parent.parent
WEB_DIR = next((p for p in [Path(os.environ.get("WEB_DIST", "")), _here / "web", _here.parent / "frontend" / "dist"]
                if str(p) not in ("", ".") and (p / "index.html").is_file()), None)

if WEB_DIR:
    logger.info(f"Serving web app from {WEB_DIR}")
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = (WEB_DIR / path).resolve()
        if path and f.is_file() and WEB_DIR.resolve() in f.parents:
            return FileResponse(f)
        # index.html must not be cached, so a new deploy is picked up on refresh.
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})
else:
    @app.get("/", tags=["Root"])
    async def root():
        return {"message": f"Welcome to {settings.APP_NAME} API", "version": settings.APP_VERSION,
                "docs": "/api/docs", "health": "/health"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
