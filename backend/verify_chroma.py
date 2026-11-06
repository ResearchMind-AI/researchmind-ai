"""
Verify embeddings are stored in ChromaDB
"""
import chromadb
from chromadb.config import Settings as ChromaSettings

# Initialize ChromaDB client
client = chromadb.PersistentClient(
    path="../data/chroma",
    settings=ChromaSettings(
        anonymized_telemetry=False,
        allow_reset=True
    )
)

# List all collections
collections = client.list_collections()
print(f"Found {len(collections)} collection(s) in ChromaDB:")
for col in collections:
    print(f"\n  Collection: {col.name}")
    print(f"  Metadata: {col.metadata}")
    print(f"  Count: {col.count()}")

    # Get a sample of data
    if col.count() > 0:
        result = col.get(limit=2, include=["documents", "metadatas"])
        print(f"  Sample documents:")
        for i, (doc, meta) in enumerate(zip(result['documents'], result['metadatas'])):
            print(f"    {i+1}. Paper ID: {meta.get('paper_id')}, Chunk: {meta.get('chunk_index')}/{meta.get('total_chunks')}")
            print(f"       Text preview: {doc[:100]}...")
