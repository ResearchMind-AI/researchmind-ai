# Deploying the ResearchMind AI POC

The POC is one Docker image plus PostgreSQL. The image runs the Streamlit UI
when `APP_MODE=ui` and the FastAPI API otherwise, on `$PORT` if the platform sets it.
All state (papers, embeddings, chat, analysis, uploads) lives in Postgres, so
there are no other volumes or services to manage.

**You need:** an OpenAI API key (required, for embeddings). Optional: an
Anthropic key (Claude for analysis/writing), free OpenAlex and Semantic Scholar
keys (more and better results). Leave optional keys **empty**, not placeholder text.

## ⭐ Recommended — Railway (stable link, no servers to manage, about $10–15/month)

Railway builds the Dockerfile straight from GitHub and redeploys on every push.

**1. Create the project**
1. Sign in at railway.com with GitHub → **New Project** → **Deploy from GitHub repo** →
   `ResearchMind-AI/researchmind-ai` (allow Railway's GitHub app to see the organisation if asked).
2. Open the new service → **Settings**:
   - **Source → Branch:** `poc` (switch to `master` once merged)
   - **Source → Root Directory:** `/backend` (where the Dockerfile is)

**2. Add the database**
In the project canvas: **+ New → Database → PostgreSQL**.

**3. Set variables** on the app service (**Variables → Raw Editor**, paste and fill in):
```
APP_MODE=ui
DATABASE_URL=${{Postgres.DATABASE_URL}}
SECRET_KEY=<long random string>
INVITE_CODE=<code your testers will need>
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=
OPENALEX_API_KEY=
SEMANTIC_SCHOLAR_API_KEY=
PUBMED_API_KEY=
OPENALEX_EMAIL=you@example.com
PUBMED_EMAIL=you@example.com
CROSSREF_EMAIL=you@example.com
```
Leave optional keys empty (not placeholder text). `${{Postgres.DATABASE_URL}}` is
Railway's reference to the database's private address. Generate `SECRET_KEY` with
`python -c "import secrets; print(secrets.token_hex(32))"`.

**4. Get the link**
Service → **Settings → Networking → Generate Domain**. Railway passes the port
in `PORT`, which the image uses automatically. Optionally set
**Deploy → Healthcheck Path** to `/_stcore/health`.

Open the `….up.railway.app` link, create your account (with the invite code),
and send testers the link + invite code. Tables are created on first start.

**Optional:** add the REST API as a second service from the same repo
(Root Directory `/backend`, `APP_MODE=api`, same variables, healthcheck `/health`).

**Keeping costs down:** in **Workspace → Usage** set a usage limit, and turn on
the service's sleep-when-idle option if testers only use it occasionally
(the first visit after a sleep takes a few seconds). Choose the region closest to
your testers in the service settings.

**Updating:** push to the `poc` branch and Railway rebuilds and redeploys.

---

## Option A — Share a test link in 5 minutes (any computer with Docker)

Best for "let someone try it today". Runs on your laptop or any VM; Cloudflare
gives you a free public HTTPS link (no account needed).

```bash
git clone https://github.com/ResearchMind-AI/researchmind-ai.git
cd researchmind-ai
git checkout poc
cp backend/.env.example backend/.env      # then edit: OPENAI_API_KEY, SECRET_KEY, INVITE_CODE
docker compose --profile share up -d --build
docker compose logs tunnel | grep trycloudflare.com
```

Send the `https://….trycloudflare.com` link **and the invite code** to your tester.
They create an account, then you can share sessions with them from the **Share** tab.
Always set `INVITE_CODE` before sharing a public link, otherwise anyone who finds
the link can sign up and use your OpenAI credit.

- Local URLs: UI http://localhost:8501 · API docs http://localhost:8000/api/docs
- The link works while your computer is on and changes if the tunnel restarts.
- Stop: `docker compose --profile share down` (data is kept in the `pgdata` volume).

## Option B — AWS (Aravind's pipeline: ECR → EC2 + RDS)

A stable, always-on URL. Terraform creates the VPC, ECR, a free-tier EC2
instance and RDS Postgres; GitHub Actions builds the image and deploys it.

**One-time setup**
1. `cd terraform/environments/prod && terraform init && terraform apply`
   (inputs: `db_password`, `ec2_public_key`). Note the outputs: EC2 IP, RDS endpoint.
2. On the EC2 instance, create `/opt/researchmind/.env` from `.env.prod.example`
   (set `DATABASE_URL` to the RDS endpoint, `SECRET_KEY`, `OPENAI_API_KEY`, optional keys).
3. In GitHub → Settings → Secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
   `EC2_HOST`, `EC2_SSH_PRIVATE_KEY` (and variable `AWS_REGION` if not us-east-1).

**Deploy**
- Automatic on every push to `master`, or run **Build and Deploy** manually from the
  Actions tab and pick the `poc` branch to deploy it before merging.
- The workflow creates/updates database tables, starts nginx + API + UI, and checks `/health`.
- Open `http://<EC2_IP>/` for the UI, `/api/docs` for the API.

Notes: the default region is `us-east-1`; for testers in Australia,
`ap-southeast-2` (Sydney) is faster (change `aws_region` and `availability_zones`).
t2.micro has 1 GB RAM; a 2 GB swap file is added at boot. For more than a few
concurrent testers use t3.small. Add a domain + HTTPS with the certbot steps in
`infra/nginx/nginx.conf`.

## Option C — Local development without Docker

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                               # set OPENAI_API_KEY; for no Postgres use:
                                                     # DATABASE_URL=sqlite:///./researchmind.db
streamlit run ui/app.py                              # UI  -> http://localhost:8501
uvicorn app.main:app --reload                        # API -> http://localhost:8000/api/docs
pytest                                               # 19 tests, no network or keys needed
```

## Checking which mode each source is in

The sidebar (**Paper sources & AI**) and `GET /health` show each source as
`full` or `limited`. Add a key to `.env`, restart, and it switches to full.

| Source | Without key | With free key |
|---|---|---|
| OpenAlex | ~100 searches/day, 20 papers/query, 1 query | ~1,000/day, 50 papers/query, 3 queries |
| Semantic Scholar | shared pool (may be slow), 20 papers, 1 query | own rate limit, 50 papers, 3 queries + recommendations |
| PubMed | 3 req/s, 20 papers | 10 req/s, 30 papers, 3 queries |
| arXiv | no key needed | — |
