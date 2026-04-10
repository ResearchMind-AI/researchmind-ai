"""
Pydantic schemas for paper management
"""
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.paper import PaperSource


# Paper Schemas
class PaperBase(BaseModel):
    """Base paper schema"""
    title: str = Field(..., min_length=1, description="Paper title")
    abstract: Optional[str] = Field(None, description="Paper abstract")
    authors: Optional[List[str]] = Field(None, description="List of author names")
    publication_date: Optional[datetime] = Field(None, description="Publication date")
    journal: Optional[str] = Field(None, description="Journal name")
    doi: Optional[str] = Field(None, description="Digital Object Identifier")
    url: Optional[str] = Field(None, description="URL to paper")
    keywords: Optional[List[str]] = Field(None, description="Keywords/topics")


class PaperCreate(PaperBase):
    """Schema for creating a paper manually"""
    source: PaperSource = Field(default=PaperSource.MANUAL_UPLOAD, description="Paper source")
    source_id: Optional[str] = Field(None, description="External source ID")
    full_text: Optional[str] = Field(None, description="Full text content")
    extra_metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class PaperUpdate(BaseModel):
    """Schema for updating a paper"""
    title: Optional[str] = Field(None, min_length=1, description="Paper title")
    abstract: Optional[str] = Field(None, description="Paper abstract")
    authors: Optional[List[str]] = Field(None, description="List of author names")
    publication_date: Optional[datetime] = Field(None, description="Publication date")
    journal: Optional[str] = Field(None, description="Journal name")
    keywords: Optional[List[str]] = Field(None, description="Keywords/topics")


class PaperResponse(PaperBase):
    """Schema for paper response"""
    id: int
    source: PaperSource
    source_id: Optional[str]
    full_text: Optional[str]
    file_path: Optional[str]
    keywords: Optional[List[str]]
    citations_count: int
    extra_metadata: Optional[Dict[str, Any]]
    embedding_generated: bool
    embedding_model: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class PaperSearchResult(BaseModel):
    """Schema for external API search results (before ingestion)"""
    title: str
    abstract: Optional[str]
    authors: Optional[List[str]]
    publication_date: Optional[str]
    journal: Optional[str]
    doi: Optional[str]
    source: PaperSource
    source_id: str
    url: Optional[str]
    relevance_score: Optional[float] = None
    citations_count: Optional[int] = 0


class PaperSearchRequest(BaseModel):
    """Schema for searching papers"""
    query: str = Field(..., min_length=1, description="Search query")
    sources: List[PaperSource] = Field(
        default=[PaperSource.PUBMED, PaperSource.OPENALEX],
        description="Sources to search"
    )
    max_results: int = Field(default=20, ge=1, le=100, description="Maximum results per source")
    start_year: Optional[int] = Field(None, description="Filter by start year")
    end_year: Optional[int] = Field(None, description="Filter by end year")


class PaperSearchResponse(BaseModel):
    """Schema for paper search response"""
    query: str
    total_results: int
    papers: List[PaperSearchResult]


class PaperIngestRequest(BaseModel):
    """Schema for ingesting papers from search results"""
    source: PaperSource
    source_id: str
    session_id: int


# Session Paper Schemas
class SessionPaperBase(BaseModel):
    """Base session paper schema"""
    paper_id: int
    notes: Optional[str] = Field(None, description="Notes or annotations")
    relevance_score: Optional[int] = Field(None, ge=1, le=5, description="Relevance score (1-5)")


class SessionPaperCreate(SessionPaperBase):
    """Schema for adding a paper to a session"""
    pass


class SessionPaperUpdate(BaseModel):
    """Schema for updating session paper"""
    notes: Optional[str] = Field(None, description="Notes or annotations")
    relevance_score: Optional[int] = Field(None, ge=1, le=5, description="Relevance score (1-5)")


class SessionPaperResponse(BaseModel):
    """Schema for session paper response"""
    id: int
    session_id: int
    paper_id: int
    added_by_user_id: int
    notes: Optional[str]
    relevance_score: Optional[int]
    added_at: datetime
    paper: PaperResponse

    class Config:
        from_attributes = True


class PaperUploadResponse(BaseModel):
    """Schema for paper upload response"""
    paper_id: int
    session_paper_id: int
    message: str
    file_path: str
