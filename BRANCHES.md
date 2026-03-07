# ResearchMindAI - Branching Strategy

## Branch Structure

### Main Branches

- **`master`** - Production-ready code
  - Protected branch
  - Only merge from `develop` after thorough testing
  - Tagged releases (v1.0.0, v1.1.0, etc.)

- **`develop`** - Integration branch for features
  - Base branch for all feature branches
  - Contains latest delivered development changes
  - Merge feature branches here first

### Feature Branches

Each feature corresponds to a phase in the implementation plan:

| Branch | Feature | Timeline | Key Components |
|--------|---------|----------|----------------|
| `feature/authentication` | User Auth & Teams | Week 1-2 | User/Team models, JWT, Auth endpoints |
| `feature/session-management` | Research Sessions | Week 3-4 | Session CRUD, Dashboard, Workspace UI |
| `feature/paper-ingestion` | Academic APIs | Week 5-6 | Semantic Scholar, PubMed, OpenAlex integrations |
| `feature/embedding-pipeline` | Vector Embeddings | Week 7 | Chunking, OpenAI embeddings, Chroma storage |
| `feature/knowledge-map` | AI Synthesis | Week 8-9 | LLM-powered theme/findings synthesis |
| `feature/rag-chat` | Q&A Chat | Week 10 | RAG pipeline, Chat interface, Citations |
| `feature/gap-analysis` | Research Gaps | Week 11 | AI gap detection, Gap visualization |
| `feature/collaboration-sharing` | Sharing | Week 12 | Session sharing, Permissions, Invite links |
| `feature/export-polish` | Export & Polish | Week 13-14 | PDF export, Testing, Bug fixes |

## Workflow

### Working on a Feature

```bash
# 1. Start from develop
git checkout develop
git pull origin develop

# 2. Create/checkout feature branch
git checkout feature/authentication

# 3. Make changes and commit
git add .
git commit -m "Add user authentication model"

# 4. Push to remote
git push origin feature/authentication

# 5. Create Pull Request to develop (on GitHub)
```

### Merging Features

```bash
# 1. Ensure feature is complete and tested
# 2. Create PR: feature/xxx → develop
# 3. Review and merge on GitHub
# 4. Delete feature branch after merge (optional)
```

### Release Process

```bash
# 1. When develop is stable and ready for release
git checkout master
git merge develop
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin master --tags
```

## Branch Dependencies

Some features depend on others:

```
master
  └── develop
      ├── feature/authentication (no dependencies)
      ├── feature/session-management (depends on: authentication)
      ├── feature/paper-ingestion (depends on: session-management)
      ├── feature/embedding-pipeline (depends on: paper-ingestion)
      ├── feature/knowledge-map (depends on: embedding-pipeline)
      ├── feature/rag-chat (depends on: embedding-pipeline)
      ├── feature/gap-analysis (depends on: knowledge-map)
      ├── feature/collaboration-sharing (depends on: session-management)
      └── feature/export-polish (depends on: all above)
```

**Recommendation:** Work sequentially on features with dependencies, or merge frequently to `develop`.

## Commit Message Convention

```
<type>: <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance tasks

**Example:**
```
feat: Add Semantic Scholar API integration

- Implement search by keyword
- Handle rate limiting (1 req/sec)
- Parse paper metadata
- Add error handling and retries

Closes #12
```

## Current Status

✅ **Initial Setup Complete**
- All branches created
- Ready to start feature development

**Next:** Start working on `feature/authentication`

## GitHub Repository

**Organization:** ResearchMind AI
**Repository:** researchmind-ai
**URL:** https://github.com/ResearchMind-AI/researchmind-ai

### Repository Links
- **Code:** https://github.com/ResearchMind-AI/researchmind-ai
- **Issues:** https://github.com/ResearchMind-AI/researchmind-ai/issues
- **Pull Requests:** https://github.com/ResearchMind-AI/researchmind-ai/pulls
- **Projects:** https://github.com/ResearchMind-AI/researchmind-ai/projects
