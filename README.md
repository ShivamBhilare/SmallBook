# SmallBook — Grounded AI Research & Study Workspace

**Master your academic literature with verifiable RAG, multi-LLM orchestration, and automated study tools.**

SmallBook is an open-source, personalized AI research assistant built as an enhanced, sovereign alternative to Google NotebookLM. It pairs high-precision document grounding with flexible model choice (OpenAI, Claude, Gemini, Groq, Ollama), cross-notebook asset sharing, and generative study tools (interactive quizzes and flashcards).

---

## 🚀 Key Features

*   **📚 Two-Stage Hierarchical RAG Pipeline**
    *   **High-Fidelity Extraction:** Converts complex PDFs into clean Markdown (preserving tables, structures, and math) via `PyMuPDF4LLM`.
    *   **Parent-Child Contextual Chunking:** Splits text with `Chonkie` into 150-token child chunks for dense vector search and 1000-token parent chunks for complete LLM context.
    *   **Dense Vectors + Cross-Encoder Reranking:** Powered by `BAAI/bge-base-en-v1.5` embeddings (768-dim) in **Qdrant** and reranked via `ms-marco-MiniLM-L-6-v2`, achieving **$<100\text{ ms}$ retrieval latency** ($p_{95} = 115.4\text{ ms}$).

*   **🎯 Verifiable Grounding & Hallucination Elimination**
    *   **Clickable Citations:** Every AI answer includes exact source citations displaying the document title, page number, and source passage.
    *   **3 Grounding Modes:**
        *   **Strict Mode:** Answers solely from your uploaded documents. Deterministically outputs *"No source found for this query"* if context is absent—eliminating AI hallucinations.
        *   **Hybrid Mode:** Prioritizes document context, but flags when falling back to general parametric knowledge.
        *   **Concise Mode:** Summarizes synthesis into high-density, bulleted study takeaways.

*   **🔄 Cross-Notebook Knowledge Sharing**
    *   Break free from monolithic folder silos. Upload foundational textbooks or papers once and seamlessly link them across multiple research notebooks without re-uploading or re-embedding.
    *   Deduplicates files automatically via **SHA-256 fingerprinting**.

*   **🔑 Cryptographic Bring-Your-Own-Key (BYOK)**
    *   **Multi-Model Orchestration:** Switch between **Groq (LLaMA 3.3 70B)**, **Google Gemini 2.0 Flash**, **OpenAI (GPT-4o)**, **Anthropic (Claude 3.5 Sonnet)**, or offline **Ollama** models using `LiteLLM`.
    *   **Zero-Knowledge Key Storage:** User API keys are encrypted at rest using **AES-256-GCM** authenticated cryptography.
    *   **Cascading Failover:** Automatically handles HTTP 429 rate limits and provider outages with seamless background failover.

*   **⚡ Asynchronous Distributed Processing**
    *   Heavy ingestion, Markdown parsing, and embedding generation are offloaded to **Celery** workers backed by **Redis**.
    *   Embeds a 200-page academic textbook in **~25 seconds** via GPU batching without freezing the web interface.

*   **🎓 Generative Study Studio**
    *   **Interactive Quizzes:** Synthesizes multiple-choice diagnostic tests directly from reading passages with instant grading and explanations.
    *   **Spaced-Repetition Flashcards:** Generates structured front/back concept flashcards with direct document traceability.
    *   Protected by distributed **Redis mutex locks** to prevent accidental duplicate requests.

---

## 📸 Visuals

### 🎥 Product Demo Walkthrough
*Watch SmallBook in action: multi-document ingestion, strict RAG grounding with page citations, and automated quiz/flashcard generation.*


https://github.com/user-attachments/assets/15d04bff-4f68-44cf-842f-c30265a316d7


### 📊 Research Dashboard & Notebook Library
*Organize your academic projects into isolated notebooks with customized multi-model LLM preferences.*
<img src="media/Dashboard.png" width="800" alt="SmallBook Research Dashboard Overview">

### 🔬 Grounded Research Workspace
*Three-pane research environment: manage sources, stream grounded answers with clickable page citations, and take notes.*
<img src="media/Workspace.png" width="800" alt="SmallBook Grounded Research Workspace">

---

## 🛠️ Installation & Setup

You can run SmallBook using **Docker Compose (Recommended)** or via **Local Development Setup**.

### Prerequisites
*   **Python 3.13+** (or [uv](https://github.com/astral-sh/uv) package manager)
*   **Docker & Docker Compose** (for containerized deployment)
*   **Supabase Account** (Free cloud PostgreSQL, Auth, and Storage)
*   **Qdrant Vector Database** (Free [Qdrant Cloud](https://cloud.qdrant.io) cluster or local Docker container)

---

### Step 1: Clone the Repository
```bash
git clone https://github.com/ShivamBhilare/SmallBook.git
cd SmallBook
```

---

### Step 2: Database & Storage Setup (Supabase)

1. Create a new project at [Supabase.com](https://supabase.com).
2. Open your project dashboard, navigate to the **SQL Editor**, and click **New Query**.
3. Copy the entire contents of [`supabase/schema.sql`](supabase/schema.sql) and paste it into the SQL editor.
4. Click **Run** to execute the script. This will set up:
   * All 17 application tables (`notebooks`, `sources`, `chat_messages`, `citations`, etc.)
   * Security helper functions (`owns_notebook`, `owns_source`)
   * Row-Level Security (RLS) policies ensuring complete multi-tenant data isolation
   * Storage bucket `user-documents` with strict folder ownership rules
   * Automated timestamp update triggers

---

### Step 3: Configure Environment Variables

Copy the example environment file and populate your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your preferred text editor:
```ini
# Supabase Configuration (From Project Settings -> API)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your-supabase-anon-key
SUPABASE_KEY=your-supabase-service-role-key
DATABASE_URL=postgresql://postgres:your-password@db.your-project-id.supabase.co:5432/postgres

# Qdrant Vector Database (Cloud or Local)
QDRANT_URL=https://your-cluster-id.cloud.qdrant.io:6333
QDRANT_API_KEY=your-qdrant-api-key

# Developer LLM Keys (For default free-tier & study tools)
GEMINI_API_KEY=your-google-gemini-api-key
GROQ_API_KEY=your-groq-api-key

# Encryption Key for BYOK Storage (Generate with the command below)
APP_ENCRYPTION_KEY=your-fernet-base64-encryption-key
```

> **Tip:** Generate a secure 32-byte Fernet key for `APP_ENCRYPTION_KEY`:
> ```bash
> python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
> ```

---

### Step 4A: Run with Docker Compose (Recommended)

Docker Compose boots the entire stack—including the web application, Celery background worker with GPU acceleration, Redis broker, and Ngrok tunnel—in one command:

```bash
docker compose up --build
```

*   **Web Application:** [http://localhost:8000](http://localhost:8000)
*   **Redis Broker:** `localhost:6379`
*   **Healthcheck:** [http://localhost:8000/health](http://localhost:8000/health)

---

### Step 4B: Local Development Setup

If you prefer running services directly on your host machine:

**1. Create & Activate Virtual Environment**
```bash
# Using uv (fastest)
uv venv --python 3.13
.venv\Scripts\activate   # Windows
source .venv/bin/activate # Mac/Linux

# OR using standard venv
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate # Mac/Linux
```

**2. Install Dependencies**
```bash
# Using uv
uv pip install -e .

# OR using standard pip
pip install -e .
```

**3. Start Redis Server**
```bash
# Using Docker
docker run -d --name smallbook_redis -p 6379:6379 redis:7-alpine

# OR local redis
redis-server
```

**4. Start Celery Worker (In a separate terminal)**
```bash
# Windows (requires solo pool or eventlet)
celery -A app.core.celery_app.celery_app worker --loglevel=info -P solo

# Linux / Mac
celery -A app.core.celery_app.celery_app worker --loglevel=info --concurrency=3
```

**5. Start FastAPI Web Server**
```bash
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## ⚙️ Configuration Reference

| Environment Variable | Required | Description |
| :--- | :---: | :--- |
| `SUPABASE_URL` | **Yes** | Supabase project API endpoint URL. |
| `SUPABASE_ANON_KEY` | **Yes** | Supabase anonymous public API key. |
| `SUPABASE_KEY` / `SERVICE_ROLE` | **Yes** | Supabase service-role secret key (for background tasks). |
| `DATABASE_URL` | **Yes** | PostgreSQL connection URI for Supabase. |
| `QDRANT_URL` | **Yes** | Qdrant endpoint URL (`https://...cloud.qdrant.io:6333` or `http://localhost:6333`). |
| `QDRANT_API_KEY` | Optional | Qdrant Cloud API key (leave empty for local Qdrant). |
| `QDRANT_TIMEOUT` | Optional | Upsert network timeout in seconds (Default: `60.0`). |
| `APP_ENCRYPTION_KEY` | **Yes** | 32-byte URL-safe base64 key for AES-256-GCM BYOK encryption. |
| `REDIS_URL` | **Yes** | Redis connection URI (Default: `redis://localhost:6379/0`). |
| `GROQ_API_KEY` | Recommended | Groq Cloud API key for ultra-fast LLaMA 3.3 generation. |
| `GEMINI_API_KEY` | Recommended | Google Gemini API key for default free-tier & study tools. |
| `HF_TOKEN` | Optional | Hugging Face token for downloading transformer weights. |
| `NGROK_AUTHTOKEN` | Optional | Ngrok authentication token for public HTTPS tunneling. |
| `NGROK_DOMAIN` | Optional | Dedicated static Ngrok domain (e.g. `your-domain.ngrok-free.app`). |

---

## 🔒 Data Privacy & Grounding Guarantees

*   **Deterministic Hallucination Prevention:** In Strict Mode, when Qdrant vector retrieval or cross-encoder reranking yields context below relevance thresholds, SmallBook outputs `"No source found for this query."` It never hallucinates citations or speculates on missing facts.
*   **Cryptographic Key Custody:** User-supplied API keys (OpenAI, Claude, Groq) are never stored in plaintext. They are encrypted at rest using **AES-256-GCM** authenticated cipher with bit-flip tamper detection.
*   **Multi-Tenant Isolation:** Complete isolation is enforced at the database level via Supabase **PostgreSQL Row-Level Security (RLS)**. No user can view, edit, or search another user's documents, vectors, or chat sessions.
*   **Sovereign Local Inference:** Compatible with local **Ollama** endpoints (`http://localhost:11434/v1`), enabling 100% offline, sovereign AI research where no data leaves your workstation.

---

## 🧪 Testing

SmallBook includes **13 automated test suites** covering cryptography, authentication, multi-tenancy, rate limits, and distributed concurrency:

```bash
# Run all unit and integration tests
pytest

# Run tests with verbose output
pytest -v

# Run security and cryptographic tests specifically
pytest tests/test_crypto.py tests/test_security_ownership.py
```

---

## 💻 Tech Stack

*   **Backend:** Python 3.13, FastAPI, Uvicorn, Celery 5.6, Redis 7, Pydantic
*   **AI / RAG Pipeline:** Qdrant Cloud (HNSW Cosine Vector DB), `LiteLLM`, `PyMuPDF4LLM`, `Chonkie` (Parent-Child chunking), `sentence-transformers` (`BAAI/bge-base-en-v1.5`, `ms-marco-MiniLM-L-6-v2`)
*   **Database & Auth:** Supabase (PostgreSQL 15), Row-Level Security (RLS), Supabase GoTrue Auth, Supabase Storage
*   **Security:** Cryptography (AES-256-GCM), SHA-256 Fingerprinting
*   **Frontend:** Jinja2 Templates, Tailwind CSS, Alpine.js, Vanilla ES6+ JavaScript, Server-Sent Events (SSE)
*   **Deployment:** Docker, Docker Compose, NVIDIA GPU Container Toolkit, Ngrok HTTPS Tunneling

