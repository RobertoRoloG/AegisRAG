<h1 align="center">AegisRAG</h1>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Next.js-000000?style=flat-square&logo=nextdotjs&logoColor=white" alt="Next.js" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/Celery-356C40?style=flat-square&logo=celery&logoColor=white" alt="Celery" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Qdrant-FF4154?style=flat-square&logo=qdrant&logoColor=white" alt="Qdrant" />
  <img src="https://img.shields.io/badge/Redis-DC382D?style=flat-square&logo=redis&logoColor=white" alt="Redis" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />
</p>

## Overview
AegisRAG is a production-grade, full-stack Corrective Retrieval-Augmented Generation (CRAG) system designed to mitigate hallucination and context irrelevance in LLM applications. Built on a decoupled microservices architecture, it orchestrates hybrid vector-lexical queries, context re-ranking, and dynamic self-correction loops to ensure accurate, verified context feeds generation.

## Tech Stack
*   **Backend:** Python 3.11+, FastAPI (ASGI Framework), Celery (Distributed Task Queue), SQLAlchemy 2.0 (Async ORM), FastEmbed (Local Embeddings & Reranking), PyPDF (Document Parsing).
*   **Frontend:** Next.js 16 (App Router), TypeScript, React 19, Tailwind CSS 4, Lucide React.
*   **Databases & Caches:** PostgreSQL 16 (Relational Metadata & History), Qdrant v1.18.2 (Vector Database supporting dense/sparse hybrid search), Redis 7 (Asynchronous Message Broker & Cache).
*   **Infrastructure & Deployment:** Docker, Docker Compose.

## Key Features
*   **Corrective RAG (CRAG) Pipeline:** Self-corrective pipeline with automated query rewriting and dynamic relevance thresholding (default `0.35` Cross-Encoder score) to filter out hallucinated context.
*   **Hybrid Semantic-Lexical Search:** Combines dense vectors (embedding-based search) and sparse vectors (BM25 keyword search) natively within Qdrant.
*   **Two-Stage Retrieval & Re-ranking:** Integrates a second-pass context optimization layer powered by `BAAI/bge-reranker-base`.
*   **Asynchronous Ingestion Queue:** Decoupled document processing (PDF parsing and chunking) using Celery background workers to keep API endpoints non-blocking.
*   **Multi-LLM Integration:** Pluggable support for local LLMs via Ollama (e.g., Llama 3) or commercial APIs including OpenAI and Groq.
*   **Session & History Tracking:** Persistent relational storage for chat sessions, message histories, and extraction metadata.

## Prerequisites
*   **OS:** Linux, macOS, or Windows (WSL 2 or PowerShell recommended)
*   **Python:** `v3.11` or higher
*   **Node.js:** `v20.x` or higher (with `npm` package manager)
*   **Docker:** Engine `v20.10+` and Docker Compose `v2.0+`

## Installation & Setup
1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/RobertoRoloG/AegisRAG.git
    cd AegisRAG
    ```

2.  **Configure Environment Variables:**
    Copy the template file to `.env` in the root and in the `backend/` directory, then adjust configuration (e.g. your `GROQ_API_KEY`):
    ```bash
    # Root
    cp .env.example .env
    # Backend
    cp .env.example backend/.env
    ```
    Key environment variables:
    *   `POSTGRES_PORT`: Host port (default `5433`).
    *   `QDRANT_PORT` / `QDRANT_GRPC_PORT`: Vector DB ports (default `6333` / `6334`).
    *   `REDIS_PORT` / `REDIS_URL`: Redis port (default `6380`).
    *   `LLM_PROVIDER`: Provider (`groq`, `ollama`, or `openai`).
    *   `LLM_MODEL`: Target model (e.g., `openai/gpt-oss-20b` for Groq, `llama3.1` for Ollama).
    *   `GROQ_API_KEY`: Required if using Groq cloud inference.

3.  **Start Services (Infrastructure Stack):**
    Spin up PostgreSQL, Qdrant, and Redis containers:
    ```bash
    docker compose up -d
    ```

4.  **Set Up Backend (FastAPI & Celery):**
    Initialize a virtual environment, install dependencies, and run database migrations:
    ```bash
    cd backend
    python -m venv .venv
    
    # Windows (PowerShell):
    .venv\Scripts\Activate.ps1
    # Linux / macOS:
    source .venv/bin/activate

    pip install --upgrade pip
    pip install -r requirements.txt

    # Apply database migrations:
    alembic upgrade head
    ```

5.  **Set Up Frontend (Next.js):**
    Install client node packages:
    ```bash
    cd ../frontend
    npm install
    ```

## Usage / Execution
Run the services across 3 separate terminal sessions:

1.  **Backend API Server (Terminal 1):**
    ```bash
    cd backend
    # Activate virtual environment
    .venv\Scripts\activate      # Windows
    # source .venv/bin/activate # Linux/macOS
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    ```

2.  **Celery Ingestion Worker (Terminal 2):**
    ```bash
    cd backend
    # Activate virtual environment
    # Windows (CRITICAL: always use --pool=solo on Windows):
    .venv\Scripts\celery.exe -A app.workers.celery_app worker --loglevel=info --pool=solo
    # Linux / macOS:
    celery -A app.workers.celery_app worker --loglevel=info
    ```

3.  **Frontend Client (Terminal 3):**
    ```bash
    cd frontend
    npm run dev
    ```

4.  **Access Main Endpoints:**
    *   **Frontend UI:** [http://localhost:3000](http://localhost:3000)
    *   **Swagger API Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
    *   **Backend Health Check:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

---

## ⚡ Important Notes & Troubleshooting

### 1. First PDF Upload Duration (One-Time Model Download)
* The **very first time** a document is uploaded, FastEmbed automatically downloads the local embedding model weights (`BAAI/bge-small-en-v1.5` ~130MB) and sparse BM25 tokenizers from HuggingFace to your local cache.
* During this initial download, document processing will appear to take ~30–60 seconds.
* **Subsequent uploads will take ~1–2 seconds**, as models are cached locally.

### 2. Windows Celery Concurrency (`--pool=solo`)
* Celery under Windows does not support `fork()`. Running Celery without `--pool=solo` will lead to worker deadlocks or task freezes during ingestion. Always include `--pool=solo` on Windows.

### 3. Port Mappings
To prevent collisions with existing system databases, AegisRAG runs with custom host ports:
* PostgreSQL: `5433` (mapped from container `5432`)
* Redis: `6380` (mapped from container `6379`)
* Qdrant: `6333` (HTTP) / `6334` (gRPC)

## Roadmap
- [ ] Add support for additional file formats (`.docx`, `.md`, `.txt`, `.html`).
- [ ] Implement Server-Sent Events (SSE) for streaming model generation.
- [ ] Integrate JWT authentication and Role-Based Access Control (RBAC).
- [ ] Optimize Docker configuration using multi-stage production builds.
- [ ] Integrate retrieval evaluation frameworks (Ragas / TruLens) to monitor retrieval quality.
