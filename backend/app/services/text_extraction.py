"""
Text extraction utilities for PDF and DOCX files
"""
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import io

import docx
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


class TextExtractor:
    """Service for extracting text from various file formats"""

    @staticmethod
    def extract_from_pdf(file_path: str) -> Dict[str, Any]:
        """Extract text and metadata from a PDF file (PyMuPDF)."""
        with open(file_path, "rb") as f:
            return TextExtractor.extract_pdf_bytes(f.read())

    @staticmethod
    def extract_pdf_bytes(data: bytes) -> Dict[str, Any]:
        """Extract text and metadata from PDF bytes (PyMuPDF)."""
        with fitz.open(stream=data, filetype="pdf") as pdf:
            meta = pdf.metadata or {}
            text = "\n\n".join(page.get_text("text") for page in pdf)
            return {
                "full_text": text.strip(),
                "page_count": pdf.page_count,
                "metadata": {"title": meta.get("title") or "", "author": meta.get("author") or "",
                             "subject": meta.get("subject") or ""},
            }

    @staticmethod
    def extract_docx_bytes(data: bytes) -> Dict[str, Any]:
        """Extract text from DOCX bytes."""
        doc = docx.Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        parts.append(cell.text)
        props = doc.core_properties
        return {"full_text": "\n\n".join(parts),
                "metadata": {"title": props.title or "", "author": props.author or "",
                             "subject": props.subject or ""}}

    @staticmethod
    def extract_from_docx(file_path: str) -> Dict[str, Any]:
        """
        Extract text and metadata from DOCX file

        Args:
            file_path: Path to DOCX file

        Returns:
            Dictionary containing text and metadata
        """
        try:
            doc = docx.Document(file_path)

            # Extract metadata from core properties
            core_props = doc.core_properties
            title = core_props.title or ''
            author = core_props.author or ''
            subject = core_props.subject or ''

            # Extract text from paragraphs
            text_parts = []
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)

            # Extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text.strip():
                            text_parts.append(cell.text)

            full_text = "\n\n".join(text_parts)

            # Build result
            result = {
                "full_text": full_text,
                "paragraph_count": len(doc.paragraphs),
                "table_count": len(doc.tables),
                "metadata": {
                    "title": title,
                    "author": author,
                    "subject": subject
                }
            }

            logger.info(f"Successfully extracted text from DOCX: {file_path}")
            return result

        except Exception as e:
            logger.error(f"Error extracting text from DOCX {file_path}: {e}")
            raise

    @staticmethod
    def extract_from_file(file_path: str) -> Dict[str, Any]:
        """
        Extract text from file, automatically detecting format

        Args:
            file_path: Path to file

        Returns:
            Dictionary containing text and metadata

        Raises:
            ValueError: If file format is not supported
        """
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == '.pdf':
            return TextExtractor.extract_from_pdf(file_path)
        elif suffix in ['.docx', '.doc']:
            return TextExtractor.extract_from_docx(file_path)
        else:
            raise ValueError(f"Unsupported file format: {suffix}")

    @staticmethod
    def extract_metadata_from_text(text: str) -> Dict[str, Any]:
        """
        Extract basic metadata from paper text
        Uses simple heuristics to identify title, authors, etc.

        Args:
            text: Paper text

        Returns:
            Dictionary containing extracted metadata
        """
        # This is a simplified version - in production, you might use
        # more sophisticated NLP techniques or libraries like GROBID

        lines = text.split('\n')
        metadata = {
            "title": None,
            "authors": None,
            "abstract": None
        }

        # Try to find title (usually first non-empty line)
        for line in lines:
            line = line.strip()
            if line and len(line) > 10:
                metadata["title"] = line
                break

        # Simple abstract detection
        abstract_keywords = ["abstract", "summary"]
        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            if any(keyword in line_lower for keyword in abstract_keywords):
                # Get next few lines as abstract
                abstract_lines = []
                for j in range(i + 1, min(i + 15, len(lines))):
                    if lines[j].strip():
                        abstract_lines.append(lines[j].strip())
                    elif abstract_lines:  # Stop at first empty line after abstract starts
                        break
                if abstract_lines:
                    metadata["abstract"] = " ".join(abstract_lines)
                break

        return metadata
