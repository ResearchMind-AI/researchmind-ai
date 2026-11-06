"""
Knowledge Map Generation Service using OpenAI
Analyzes papers to extract concepts, themes, and relationships
"""
import logging
import json
from typing import List, Dict, Any, Tuple
from openai import AsyncOpenAI
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.paper import Paper, SessionPaper
from app.models.knowledge_map import KnowledgeNode, NodeRelationship, NodeType, RelationType

logger = logging.getLogger(__name__)


class KnowledgeMapService:
    """Service for generating knowledge maps from research papers"""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = getattr(settings, 'CHAT_MODEL', 'gpt-4o-mini')

    async def generate_knowledge_map(
        self,
        session_id: int,
        db: DBSession,
        max_nodes: int = 20,
        force_regenerate: bool = False
    ) -> Tuple[int, int]:
        """
        Generate knowledge map for a research session

        Args:
            session_id: Research session ID
            db: Database session
            max_nodes: Maximum number of nodes to generate
            force_regenerate: Whether to regenerate if map exists

        Returns:
            Tuple of (nodes_created, relationships_created)
        """
        # Check if map already exists
        if not force_regenerate:
            existing_nodes = db.query(KnowledgeNode).filter(
                KnowledgeNode.session_id == session_id
            ).count()
            if existing_nodes > 0:
                logger.info(f"Knowledge map already exists for session {session_id}")
                return (0, 0)

        # Delete existing map if regenerating
        if force_regenerate:
            db.query(NodeRelationship).filter(NodeRelationship.session_id == session_id).delete()
            db.query(KnowledgeNode).filter(KnowledgeNode.session_id == session_id).delete()
            db.commit()

        # Get all papers in the session
        session_papers = db.query(SessionPaper).filter(
            SessionPaper.session_id == session_id
        ).all()

        if not session_papers:
            logger.warning(f"No papers found for session {session_id}")
            return (0, 0)

        # Gather paper summaries
        paper_summaries = []
        for sp in session_papers:
            paper = db.query(Paper).filter(Paper.id == sp.paper_id).first()
            if paper:
                summary = {
                    "id": paper.id,
                    "title": paper.title,
                    "abstract": paper.abstract or "",
                    "authors": paper.authors or [],
                    "year": paper.publication_date.year if paper.publication_date else None
                }
                paper_summaries.append(summary)

        # Extract concepts and themes using AI
        concepts_data = await self._extract_concepts(paper_summaries, max_nodes)

        # Create nodes in database
        nodes_created = 0
        node_map = {}  # Map from label to node object

        for concept in concepts_data.get("concepts", []):
            node = KnowledgeNode(
                session_id=session_id,
                label=concept["label"],
                description=concept.get("description"),
                node_type=NodeType(concept.get("type", "concept")),
                importance_score=concept.get("importance", 0.5),
                paper_ids=concept.get("paper_ids", []),
                citation_count=len(concept.get("paper_ids", [])),
                summary=concept.get("summary"),
                keywords=concept.get("keywords", [])
            )
            db.add(node)
            node_map[concept["label"]] = node
            nodes_created += 1

        db.commit()

        # Extract relationships
        relationships_data = await self._extract_relationships(
            paper_summaries,
            list(node_map.keys())
        )

        # Create relationships in database
        relationships_created = 0
        for rel in relationships_data.get("relationships", []):
            source_label = rel.get("source")
            target_label = rel.get("target")

            if source_label in node_map and target_label in node_map:
                relationship = NodeRelationship(
                    session_id=session_id,
                    source_node_id=node_map[source_label].id,
                    target_node_id=node_map[target_label].id,
                    relation_type=RelationType(rel.get("type", "related_to")),
                    strength=rel.get("strength", 0.5),
                    description=rel.get("description"),
                    paper_ids=rel.get("paper_ids", [])
                )
                db.add(relationship)
                relationships_created += 1

        db.commit()

        logger.info(f"Generated knowledge map: {nodes_created} nodes, {relationships_created} relationships")
        return (nodes_created, relationships_created)

    async def _extract_concepts(
        self,
        paper_summaries: List[Dict[str, Any]],
        max_concepts: int
    ) -> Dict[str, Any]:
        """
        Extract key concepts and themes from papers using AI

        Args:
            paper_summaries: List of paper summary dictionaries
            max_concepts: Maximum number of concepts to extract

        Returns:
            Dictionary containing extracted concepts
        """
        prompt = f"""Analyze the following research papers and extract the {max_concepts} most important concepts, themes, methods, and findings.

Papers:
{json.dumps(paper_summaries, indent=2)}

For each concept, provide:
1. label: A concise label (2-5 words)
2. description: A brief description (1-2 sentences)
3. type: One of [concept, method, finding, gap, trend]
4. importance: Float between 0-1 (how central/important this concept is)
5. paper_ids: List of paper IDs that discuss this concept
6. summary: A detailed summary (2-3 sentences) explaining this concept across the papers
7. keywords: List of related keywords

Return ONLY a valid JSON object with this structure:
{{
  "concepts": [
    {{
      "label": "Machine Learning in Diagnostics",
      "description": "Application of ML algorithms for medical diagnosis",
      "type": "method",
      "importance": 0.9,
      "paper_ids": [1, 3, 5],
      "summary": "Multiple papers discuss...",
      "keywords": ["deep learning", "classification", "diagnosis"]
    }}
  ]
}}

Focus on:
- Main research topics and themes
- Key methodologies used
- Important findings and results
- Research gaps identified
- Emerging trends

Return valid JSON only, no other text."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a research analysis AI that extracts key concepts from academic papers. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )

            content = response.choices[0].message.content.strip()

            # Try to parse JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # If response has markdown code blocks, extract JSON
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                return json.loads(content)

        except Exception as e:
            logger.error(f"Error extracting concepts: {e}")
            return {"concepts": []}

    async def _extract_relationships(
        self,
        paper_summaries: List[Dict[str, Any]],
        concept_labels: List[str]
    ) -> Dict[str, Any]:
        """
        Extract relationships between concepts using AI

        Args:
            paper_summaries: List of paper summary dictionaries
            concept_labels: List of concept labels to find relationships between

        Returns:
            Dictionary containing extracted relationships
        """
        prompt = f"""Given these research papers and the identified concepts, identify meaningful relationships between the concepts.

Papers:
{json.dumps(paper_summaries[:10], indent=2)}  # Limit for token size

Concepts:
{json.dumps(concept_labels, indent=2)}

For each relationship, provide:
1. source: The source concept label (must match exactly from the concepts list)
2. target: The target concept label (must match exactly from the concepts list)
3. type: One of [related_to, depends_on, contradicts, supports, extends]
4. strength: Float between 0-1 (confidence in this relationship)
5. description: Brief explanation of the relationship
6. paper_ids: List of paper IDs that evidence this relationship

Return ONLY a valid JSON object:
{{
  "relationships": [
    {{
      "source": "Deep Learning",
      "target": "Image Classification",
      "type": "supports",
      "strength": 0.8,
      "description": "Deep learning techniques enable...",
      "paper_ids": [1, 3]
    }}
  ]
}}

Focus on:
- How concepts build upon each other (extends, depends_on)
- Supporting evidence between methods and findings (supports)
- Contradictory findings (contradicts)
- General associations (related_to)

Return valid JSON only, no other text."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a research analysis AI that identifies relationships between concepts. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1500
            )

            content = response.choices[0].message.content.strip()

            # Try to parse JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # If response has markdown code blocks, extract JSON
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                return json.loads(content)

        except Exception as e:
            logger.error(f"Error extracting relationships: {e}")
            return {"relationships": []}
