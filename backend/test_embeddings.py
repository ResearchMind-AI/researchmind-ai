"""
Quick test script to verify OpenAI embeddings work
"""
import asyncio
from app.config import settings
from app.services.embedding_service import EmbeddingService


async def test_embeddings():
    """Test embedding generation"""
    print(f"Testing embeddings with model: {settings.EMBEDDING_MODEL}")
    print(f"API key present: {bool(settings.OPENAI_API_KEY)}")
    print(f"API key starts with: {settings.OPENAI_API_KEY[:10]}..." if settings.OPENAI_API_KEY else "No API key")

    service = EmbeddingService()

    # Test simple embedding
    text = "This is a test paper about machine learning in healthcare."
    print(f"\nGenerating embedding for: {text}")

    try:
        embedding = await service.generate_embedding(text)
        print(f"SUCCESS! Generated embedding with {len(embedding)} dimensions")
        print(f"First 5 values: {embedding[:5]}")

        # Test paper embedding
        print("\nTesting paper embedding with chunking...")
        chunks, embeddings = await service.embed_paper(
            title="Test Paper",
            abstract="This is a test abstract about AI in medicine.",
            full_text=None
        )
        print(f"SUCCESS! Generated {len(chunks)} chunks with embeddings")
        for i, chunk in enumerate(chunks):
            print(f"  Chunk {i+1}: {chunk[:80]}...")

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_embeddings())
