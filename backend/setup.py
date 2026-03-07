"""
Setup script for ResearchMindAI backend
Run this after installing dependencies to verify setup
"""
import sys
import os

def check_environment():
    """Check if environment is set up correctly"""
    print("Checking ResearchMindAI Backend Setup...")
    print("=" * 50)

    # Check Python version
    print(f"✓ Python version: {sys.version.split()[0]}")
    if sys.version_info < (3, 11):
        print("⚠️  Warning: Python 3.11+ recommended")

    # Check if .env exists
    if os.path.exists(".env"):
        print("✓ .env file found")
    else:
        print("⚠️  .env file not found - copy from .env.example")

    # Try importing key dependencies
    dependencies = [
        "fastapi",
        "sqlalchemy",
        "redis",
        "celery",
        "openai",
        "chromadb",
        "langchain"
    ]

    print("\nChecking dependencies:")
    for dep in dependencies:
        try:
            __import__(dep)
            print(f"  ✓ {dep}")
        except ImportError:
            print(f"  ✗ {dep} - run 'pip install -r requirements.txt'")

    # Check if data directories exist
    print("\nChecking data directories:")
    data_dirs = ["../data/uploads", "../data/chroma", "../data/postgres", "../data/redis"]
    for dir_path in data_dirs:
        if os.path.exists(dir_path):
            print(f"  ✓ {dir_path}")
        else:
            print(f"  ℹ  {dir_path} - will be created on startup")

    print("\n" + "=" * 50)
    print("Setup check complete!")
    print("\nNext steps:")
    print("1. Ensure Docker services are running:")
    print("   cd docker && docker-compose -f docker-compose.dev.yml up -d")
    print("2. Add your OpenAI API key to .env")
    print("3. Run the app: python -m app.main")

if __name__ == "__main__":
    check_environment()
